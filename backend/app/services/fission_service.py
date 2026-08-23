from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from backend.app.graphs.fission_agent import run_fission
from backend.app.models.enums import FissionPhase, JobStatus, StoryStatus
from backend.app.services.story_repository import StoryRepository

logger = logging.getLogger(__name__)


def _format_exc(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__


class FissionService:
    def __init__(self, repo: StoryRepository | None = None):
        self.repo = repo or StoryRepository()

    async def create_story(self, inspiration: str) -> str:
        return await self.repo.create_story_indexed(inspiration.strip())

    async def start_fission(self, story_id: str) -> str:
        try:
            self.repo.load_meta(story_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail="story not found") from e
        running = await self.repo.find_running_fission(story_id)
        if running is not None:
            raise HTTPException(status_code=409, detail="fission already running")
        job = await self.repo.create_job(story_id)
        asyncio.create_task(self._run_job(job.job_id, story_id))
        return job.job_id

    def _mark_story_failed(self, story_id: str, error: str) -> None:
        self.repo.append_event(
            story_id,
            phase=FissionPhase.failed,
            type="error",
            message=f"裂变失败：{error}",
            payload={"error": error},
        )
        meta = self.repo.load_meta(story_id)
        meta.status = StoryStatus.failed
        meta.phase = FissionPhase.failed
        self.repo.save_meta(meta)

    async def _run_job(self, job_id: str, story_id: str) -> None:
        await self.repo.update_job(job_id, status=JobStatus.running)
        try:
            await run_fission(story_id)
            await self.repo.update_job(job_id, status=JobStatus.succeeded)
        except Exception as exc:  # noqa: BLE001
            error = _format_exc(exc)
            logger.exception("fission job %s failed for story %s", job_id, story_id)
            try:
                self._mark_story_failed(story_id, error)
                await self.repo.sync_story_row(story_id)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist story failure for %s", story_id)
            await self.repo.update_job(job_id, status=JobStatus.failed, error=error)
