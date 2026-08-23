from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, story_dir
from backend.app.models.enums import JobStatus, ProduceStatus
from backend.app.services.asset_pipeline import generate_cast_images
from backend.app.services.produce_service import ProduceService
from backend.app.services.story_repository import StoryRepository


@pytest.fixture
def quota_story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_engine_for_tests()
    repo = StoryRepository()
    sid = repo.create_story("测试")
    blueprint = {
        "story_id": sid,
        "produce_status": "none",
        "characters": [
            {
                "character_id": "c1",
                "name": "甲",
                "appearance_prompt": "x",
                "traits": [],
                "status": "pending",
            }
        ],
        "scenes": [],
        "nodes": [],
        "plot_lines": [],
    }
    story_dir(sid).mkdir(parents=True, exist_ok=True)
    blueprint_path(sid).write_text(json.dumps(blueprint), encoding="utf-8")
    return sid


@pytest.mark.asyncio
async def test_quota_pause_no_retry_loop(quota_story: str) -> None:
    await init_db()
    repo = StoryRepository()
    calls = {"n": 0}

    async def fail_png(**_kwargs):
        calls["n"] += 1
        raise QuotaExhaustedError(
            provider="geekai", model="gpt-image-2", http_status=402, raw_message="balance"
        )

    with patch(
        "backend.app.services.asset_pipeline.GeekAIImageClient.generate_png",
        new=AsyncMock(side_effect=fail_png),
    ), patch(
        "backend.app.services.asset_pipeline.GeekAIImageClient.aclose",
        new=AsyncMock(),
    ):
        job = await repo.create_job(quota_story)
        with pytest.raises(QuotaExhaustedError):
            await generate_cast_images(quota_story, repo=repo, job_id=job.job_id)

    assert calls["n"] == 1
    meta = repo.load_meta(quota_story)
    assert meta.produce_status == ProduceStatus.paused
    updated = await repo.get_job(job.job_id)
    assert updated is not None
    assert updated.status == JobStatus.paused


@pytest.mark.asyncio
async def test_resume_skips_ready_and_continues(quota_story: str) -> None:
    await init_db()
    repo = StoryRepository()
    bp = json.loads(blueprint_path(quota_story).read_text(encoding="utf-8"))
    bp["characters"][0]["status"] = "ready"
    bp["characters"][0]["image_path"] = "assets/characters/c1.png"
    blueprint_path(quota_story).write_text(json.dumps(bp), encoding="utf-8")
    meta = repo.load_meta(quota_story)
    meta.produce_status = ProduceStatus.paused
    meta.produce_paused_from = ProduceStatus.cast.value
    repo.save_meta(meta)

    with patch(
        "backend.app.services.produce_service.run_produce_static_graph",
        new=AsyncMock(return_value={"cast": {"generated": 0}}),
    ) as static_mock, patch(
        "backend.app.services.produce_service.run_video_generation",
        new=AsyncMock(return_value={"ok": True}),
    ), patch(
        "backend.app.services.produce_service.run_qc_loop",
        new=AsyncMock(return_value={"ok": True, "pass": 1, "fail": 0}),
    ):
        svc = ProduceService(repo)
        await svc.run_produce(quota_story)

    static_mock.assert_awaited_once()
