from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, story_dir
from backend.app.models.enums import ProduceStatus
from backend.app.services.asset_pipeline import generate_cast_images
from backend.app.services.story_repository import StoryRepository


@pytest.fixture
def asset_story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_engine_for_tests()
    repo = StoryRepository()
    sid = repo.create_story("测试故事")
    blueprint = {
        "story_id": sid,
        "inspiration": "测试故事",
        "produce_status": "none",
        "characters": [
            {
                "character_id": "c_1",
                "name": "甲",
                "appearance_prompt": "武士",
                "traits": [],
                "image_path": None,
                "status": "pending",
            },
            {
                "character_id": "c_2",
                "name": "乙",
                "appearance_prompt": "谋士",
                "traits": [],
                "image_path": None,
                "status": "pending",
            },
        ],
        "scenes": [],
        "nodes": [],
        "plot_lines": [],
    }
    story_dir(sid).mkdir(parents=True, exist_ok=True)
    blueprint_path(sid).write_text(json.dumps(blueprint), encoding="utf-8")
    return sid


@pytest.mark.asyncio
async def test_generate_cast_pauses_on_quota(asset_story: str) -> None:
    await init_db()
    repo = StoryRepository()
    job = await repo.create_job(asset_story)

    call_count = 0

    async def fake_png(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise QuotaExhaustedError(
                provider="geekai",
                model="gpt-image-2",
                http_status=402,
                raw_message="insufficient balance",
            )
        dest = kwargs["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"png")
        return dest

    with patch(
        "backend.app.services.asset_pipeline.GeekAIImageClient.generate_png",
        new=AsyncMock(side_effect=fake_png),
    ):
        with patch(
            "backend.app.services.asset_pipeline.GeekAIImageClient.aclose",
            new=AsyncMock(),
        ):
            with pytest.raises(QuotaExhaustedError):
                await generate_cast_images(asset_story, repo=repo, job_id=job.job_id)

    meta = repo.load_meta(asset_story)
    assert meta.produce_status == ProduceStatus.paused
    assert meta.produce_paused_from == ProduceStatus.cast.value
    bp = json.loads(blueprint_path(asset_story).read_text(encoding="utf-8"))
    ready = [c for c in bp["characters"] if c["status"] == "ready"]
    assert len(ready) == 1
    updated_job = await repo.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status.value == "paused"
    assert call_count == 2
