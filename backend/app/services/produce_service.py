from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.infrastructure.paths import blueprint_path
from backend.app.models.enums import FissionPhase, JobStatus, JobType, ProduceStatus
from backend.app.graphs.produce_graph import run_produce_static_graph
from backend.app.services.produce_state import enter_awaiting_video, load_blueprint, save_blueprint
from backend.app.services.segment_plan import (
    prefetch_frame_stats,
    prefetch_segments,
    prefetch_synthetic_segments,
)
from backend.app.services.story_repository import StoryRepository
from backend.app.services.video_pipeline import (
    run_first_frames_phase,
    run_qc_loop,
    run_video_generation,
)

logger = logging.getLogger(__name__)


def _resume_from_pause(repo: StoryRepository, story_id: str) -> None:
    meta = repo.load_meta(story_id)
    if meta.produce_status == ProduceStatus.paused and meta.produce_paused_from:
        meta.produce_status = ProduceStatus(meta.produce_paused_from)
        meta.produce_paused_from = None
        meta.produce_pause_reason = None
        repo.save_meta(meta)


def _infer_produce_resume_status(blueprint: dict) -> ProduceStatus:
    """根据 blueprint 实际进度推断应从哪一生产阶段继续。"""
    characters = blueprint.get("characters") or []
    scenes = blueprint.get("scenes") or []
    nodes = blueprint.get("nodes") or []
    segments = blueprint.get("segments") or []
    prefetch = [s for s in segments if s.get("produce_tier", "prefetch") == "prefetch"]

    if characters and any(c.get("status") != "ready" for c in characters):
        return ProduceStatus.none
    if scenes and any(s.get("status") != "ready" for s in scenes):
        return ProduceStatus.cast
    synthetic_pf = prefetch_synthetic_segments(segments)
    if synthetic_pf and any(not s.get("first_frame_path") for s in synthetic_pf):
        return ProduceStatus.frames
    if nodes and any(n.get("shot_prompt_status") != "ready" for n in nodes):
        return ProduceStatus.prompts
    if prefetch and any(s.get("video_status") != "ready" for s in prefetch):
        if synthetic_pf and all(s.get("first_frame_path") for s in synthetic_pf):
            return ProduceStatus.awaiting_video
        return ProduceStatus.videos
    if prefetch and any(
        s.get("video_status") == "ready" and s.get("qc_status") not in ("pass", "fail")
        for s in prefetch
    ):
        return ProduceStatus.qc
    if prefetch:
        return ProduceStatus.videos
    return ProduceStatus.scenes


def _resume_from_failed(repo: StoryRepository, story_id: str) -> None:
    """失败后重试：按 blueprint 进度恢复到对应阶段。"""
    meta = repo.load_meta(story_id)
    if meta.produce_status != ProduceStatus.failed:
        return
    blueprint = load_blueprint(story_id)
    status = _infer_produce_resume_status(blueprint)

    meta.produce_status = status
    meta.produce_paused_from = None
    meta.produce_pause_reason = None
    blueprint["produce_status"] = status.value
    save_blueprint(story_id, blueprint)
    repo.save_meta(meta)


class ProduceService:
    def __init__(self, repo: StoryRepository | None = None):
        self.repo = repo or StoryRepository()

    async def start_produce(self, story_id: str) -> str:
        self._ensure_story(story_id)
        if await self.repo.find_running_job(story_id, JobType.produce):
            raise HTTPException(status_code=409, detail="produce already running")
        meta = self.repo.load_meta(story_id)
        if meta.produce_status == ProduceStatus.paused:
            raise HTTPException(status_code=409, detail="produce paused; call .../produce/resume")
        if meta.produce_status == ProduceStatus.awaiting_video:
            raise HTTPException(
                status_code=409,
                detail="assets ready; call .../produce/videos to generate videos",
            )
        _resume_from_failed(self.repo, story_id)
        self.repo.append_event(
            story_id,
            phase=FissionPhase.done,
            type="phase",
            message="生产已开始",
            payload={"stage": "produce"},
        )
        job = await self.repo.create_job(story_id, JobType.produce)
        asyncio.create_task(self._run_job(job.job_id, story_id))
        return job.job_id

    async def resume_produce(self, story_id: str) -> str:
        self._ensure_story(story_id)
        meta = self.repo.load_meta(story_id)
        if meta.produce_status != ProduceStatus.paused:
            raise HTTPException(status_code=400, detail="produce is not paused")
        if await self.repo.find_running_job(story_id, JobType.produce):
            raise HTTPException(status_code=409, detail="produce already running")
        job = await self.repo.create_job(story_id, JobType.produce)
        asyncio.create_task(self._run_job(job.job_id, story_id))
        return job.job_id

    async def start_video_produce(self, story_id: str) -> str:
        """素材与首帧完成后，用户确认再出片。"""
        self._ensure_story(story_id)
        if await self.repo.find_running_job(story_id, JobType.produce):
            raise HTTPException(status_code=409, detail="produce already running")
        meta = self.repo.load_meta(story_id)
        if meta.produce_status == ProduceStatus.paused:
            raise HTTPException(status_code=409, detail="produce paused; call .../produce/resume")
        if meta.produce_status not in (ProduceStatus.awaiting_video, ProduceStatus.videos):
            raise HTTPException(
                status_code=400,
                detail="produce is not awaiting video generation",
            )
        if meta.produce_status == ProduceStatus.awaiting_video:
            blueprint = load_blueprint(story_id)
            meta.produce_status = ProduceStatus.videos
            blueprint["produce_status"] = ProduceStatus.videos.value
            save_blueprint(story_id, blueprint)
            self.repo.save_meta(meta)
        self.repo.append_event(
            story_id,
            phase=FissionPhase.done,
            type="phase",
            message="开始生成视频",
            payload={"stage": "videos"},
        )
        job = await self.repo.create_job(story_id, JobType.produce)
        asyncio.create_task(self._run_job(job.job_id, story_id, video_only=True))
        return job.job_id

    def _ensure_story(self, story_id: str) -> None:
        try:
            self.repo.load_meta(story_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail="story not found") from e
        if not blueprint_path(story_id).exists():
            raise HTTPException(status_code=400, detail="blueprint not found; run persist first")

    async def _run_job(self, job_id: str, story_id: str, *, video_only: bool = False) -> None:
        await self.repo.update_job(job_id, status=JobStatus.running)
        try:
            await self.run_produce(story_id, job_id=job_id, video_only=video_only)
            meta = self.repo.load_meta(story_id)
            if meta.produce_status != ProduceStatus.paused:
                await self.repo.update_job(job_id, status=JobStatus.succeeded)
        except QuotaExhaustedError:
            logger.info("produce job %s paused (quota) story %s", job_id, story_id)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            logger.exception("produce job %s failed story %s", job_id, story_id)
            meta = self.repo.load_meta(story_id)
            meta.produce_status = ProduceStatus.failed
            self.repo.save_meta(meta)
            self.repo.append_event(
                story_id,
                phase=FissionPhase.done,
                type="error",
                message=f"生产失败：{error}",
                payload={"error": error},
            )
            await self.repo.update_job(job_id, status=JobStatus.failed, error=error)

    async def run_produce(
        self, story_id: str, *, job_id: str | None = None, video_only: bool = False
    ) -> dict:
        if not video_only:
            _resume_from_pause(self.repo, story_id)
            meta = self.repo.load_meta(story_id)

            if meta.produce_status in (
                ProduceStatus.none,
                ProduceStatus.cast,
                ProduceStatus.scenes,
                ProduceStatus.prompts,
            ):
                await run_produce_static_graph(story_id, repo=self.repo, job_id=job_id)
                meta = self.repo.load_meta(story_id)
                if meta.produce_status == ProduceStatus.paused:
                    return {"stage": "static_paused"}

            meta = self.repo.load_meta(story_id)
            if meta.produce_status in (ProduceStatus.prompts, ProduceStatus.frames):
                await run_first_frames_phase(story_id, repo=self.repo, job_id=job_id)
                meta = self.repo.load_meta(story_id)
                if meta.produce_status == ProduceStatus.paused:
                    return {"stage": "frames_paused"}
                blueprint = load_blueprint(story_id)
                enter_awaiting_video(self.repo, story_id, blueprint)
                return {"stage": "awaiting_video"}

        meta = self.repo.load_meta(story_id)
        if meta.produce_status in (
            ProduceStatus.awaiting_video,
            ProduceStatus.frames,
            ProduceStatus.videos,
        ):
            if meta.produce_status == ProduceStatus.awaiting_video:
                blueprint = load_blueprint(story_id)
                meta.produce_status = ProduceStatus.videos
                blueprint["produce_status"] = ProduceStatus.videos.value
                save_blueprint(story_id, blueprint)
                self.repo.save_meta(meta)
            await run_video_generation(story_id, repo=self.repo, job_id=job_id)
            meta = self.repo.load_meta(story_id)
            if meta.produce_status == ProduceStatus.paused:
                return {"stage": "video_paused"}

        meta = self.repo.load_meta(story_id)
        if meta.produce_status in (ProduceStatus.videos, ProduceStatus.qc):
            await run_qc_loop(story_id, repo=self.repo, job_id=job_id)

        await self.repo.sync_story_row(story_id)
        final = self.repo.load_meta(story_id).produce_status.value
        return {"stage": "done", "produce_status": final}

    async def get_produce_summary(self, story_id: str) -> dict:
        from backend.app.services.assets_service import AssetsService

        base = AssetsService(self.repo).get_assets_summary(story_id)
        blueprint = load_blueprint(story_id)
        segments = blueprint.get("segments") or []
        prefetch = [
            s for s in segments if s.get("produce_tier", "prefetch") == "prefetch"
        ]
        on_demand = [s for s in segments if s.get("produce_tier") == "on_demand"]
        base["videos"] = {
            "total": len(prefetch),
            "ready": sum(1 for s in prefetch if s.get("video_status") == "ready"),
        }
        base["on_demand"] = {
            "total": len(on_demand),
            "ready": sum(1 for s in on_demand if s.get("video_status") == "ready"),
        }
        frame_stats = prefetch_frame_stats(segments)
        base.update(frame_stats)
        base["frames"] = frame_stats["synthetic_frames"]
        base["qc"] = {
            "pass": sum(1 for s in prefetch if s.get("qc_status") == "pass"),
            "fail": sum(1 for s in prefetch if s.get("qc_status") == "fail"),
            "pending": sum(
                1
                for s in prefetch
                if s.get("video_status") == "ready"
                and s.get("qc_status") not in ("pass", "fail")
            ),
        }
        job = await self.repo.find_running_job(story_id, JobType.produce)
        base["active_job"] = (
            {"job_id": job.job_id, "status": job.status.value}
            if job is not None
            else None
        )
        return base
