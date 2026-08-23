#!/usr/bin/env python3
"""独立运行 produce（不经 uvicorn --reload），避免热重载杀后台任务。"""
from __future__ import annotations

import argparse
import asyncio
import sys

from backend.app.infrastructure.db import init_db
from backend.app.models.enums import JobStatus, JobType
from backend.app.services.produce_service import ProduceService
from backend.app.services.story_repository import StoryRepository


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run story produce pipeline")
    parser.add_argument("story_id", help="story id")
    args = parser.parse_args()

    await init_db()
    repo = StoryRepository()
    svc = ProduceService(repo)
    job = await repo.create_job(args.story_id, JobType.produce)
    await repo.update_job(job.job_id, status=JobStatus.running)
    print(f"produce job={job.job_id} story={args.story_id}", flush=True)
    try:
        result = await svc.run_produce(args.story_id, job_id=job.job_id)
        meta = repo.load_meta(args.story_id)
        if meta.produce_status.value != "paused":
            await repo.update_job(job.job_id, status=JobStatus.succeeded)
        print(result, flush=True)
        return 0
    except Exception as exc:
        await repo.update_job(job.job_id, status=JobStatus.failed, error=str(exc))
        print(f"failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
