from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.infrastructure.paths import blueprint_path
from backend.app.models.enums import FissionPhase, JobStatus, JobType, ProduceStatus
from backend.app.graphs.produce_graph import run_produce_static_graph
from backend.app.services.produce_state import load_blueprint
from backend.app.services.segment_plan import prefetch_frame_stats
from backend.app.services.story_repository import StoryRepository

logger = logging.getLogger(__name__)


class AssetsService:
    def __init__(self, repo: StoryRepository | None = None):
        self.repo = repo or StoryRepository()

    async def start_assets(self, story_id: str) -> str:
        try:
            self.repo.load_meta(story_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail="story not found") from e
        if not blueprint_path(story_id).exists():
            raise HTTPException(status_code=400, detail="blueprint not found; run persist first")
        running = await self.repo.find_running_job(story_id, JobType.assets)
        if running is not None:
            raise HTTPException(status_code=409, detail="asset generation already running")
        meta = self.repo.load_meta(story_id)
        if meta.produce_status == ProduceStatus.paused:
            raise HTTPException(
                status_code=409,
                detail="produce paused; call POST .../assets/resume",
            )
        job = await self.repo.create_job(story_id, JobType.assets)
        asyncio.create_task(self._run_job(job.job_id, story_id))
        return job.job_id

    async def resume_assets(self, story_id: str) -> str:
        try:
            meta = self.repo.load_meta(story_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail="story not found") from e
        if meta.produce_status != ProduceStatus.paused:
            raise HTTPException(status_code=400, detail="produce is not paused")
        running = await self.repo.find_running_job(story_id, JobType.assets)
        if running is not None:
            raise HTTPException(status_code=409, detail="asset generation already running")
        job = await self.repo.create_job(story_id, JobType.assets)
        asyncio.create_task(self._run_job(job.job_id, story_id, resume=True))
        return job.job_id

    async def _run_job(self, job_id: str, story_id: str, *, resume: bool = False) -> None:
        await self.repo.update_job(job_id, status=JobStatus.running)
        try:
            await run_produce_static_graph(story_id, repo=self.repo, job_id=job_id)
            meta = self.repo.load_meta(story_id)
            if meta.produce_status != ProduceStatus.paused:
                await self.repo.update_job(job_id, status=JobStatus.succeeded)
        except QuotaExhaustedError:
            logger.info("asset job %s paused for story %s (quota)", job_id, story_id)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            logger.exception("asset job %s failed for story %s", job_id, story_id)
            self.repo.append_event(
                story_id,
                phase=FissionPhase.done,
                type="error",
                message=f"素材生成失败：{error}",
                payload={"error": error},
            )
            await self.repo.update_job(job_id, status=JobStatus.failed, error=error)

    def get_assets_summary(self, story_id: str) -> dict:
        blueprint = load_blueprint(story_id)
        characters = blueprint.get("characters") or []
        scenes = blueprint.get("scenes") or []
        nodes = blueprint.get("nodes") or []
        segments = blueprint.get("segments") or []
        meta = self.repo.load_meta(story_id)
        return {
            "story_id": story_id,
            "produce_status": meta.produce_status.value,
            "produce_paused_from": meta.produce_paused_from,
            "produce_pause_reason": meta.produce_pause_reason,
            "characters": {
                "total": len(characters),
                "ready": sum(1 for c in characters if c.get("status") == "ready"),
            },
            "scenes": {
                "total": len(scenes),
                "ready": sum(1 for s in scenes if s.get("status") == "ready"),
            },
            "shot_prompts": {
                "total": len(nodes),
                "ready": sum(1 for n in nodes if n.get("shot_prompt_status") == "ready"),
            },
            "segments": {
                "total": len(segments),
                "synthetic": sum(
                    1 for s in segments if s.get("first_frame_source") == "synthetic"
                ),
                "prev_last_frame": sum(
                    1 for s in segments if s.get("first_frame_source") == "prev_last_frame"
                ),
            },
            **prefetch_frame_stats(segments),
            "frames": prefetch_frame_stats(segments)["synthetic_frames"],
        }
