from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, story_dir
from backend.app.models.enums import ProduceStatus
from backend.app.services.first_frame import bind_prev_last_frame
from backend.app.services.produce_service import ProduceService, _infer_produce_resume_status
from backend.app.services.produce_state import load_blueprint, save_blueprint
from backend.app.services.story_repository import StoryRepository


@pytest.fixture
def produce_story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_engine_for_tests()
    repo = StoryRepository()
    sid = repo.create_story("测试")
    meta = repo.load_meta(sid)
    meta.produce_status = ProduceStatus.prompts
    repo.save_meta(meta)
    blueprint = {
        "story_id": sid,
        "produce_status": "prompts",
        "characters": [],
        "scenes": [],
        "nodes": [],
        "plot_lines": [],
        "segments": [
            {
                "segment_id": "seg_a_b",
                "from_node_id": "n_a",
                "to_node_id": "n_b",
                "prompt_node_id": "n_b",
                "first_frame_source": "synthetic",
                "first_frame_path": None,
                "video_status": "pending",
                "qc_status": "pending",
            }
        ],
    }
    story_dir(sid).mkdir(parents=True, exist_ok=True)
    blueprint_path(sid).write_text(json.dumps(blueprint), encoding="utf-8")
    return sid


def test_bind_prev_last_frame(tmp_path: Path) -> None:
    story_id = "s1"
    root = tmp_path / "data" / "stories" / story_id
    pred_last = root / "assets" / "frames" / "seg_x_a_last.png"
    pred_last.parent.mkdir(parents=True)
    pred_last.write_bytes(b"frame")
    monkeypatch_story = story_id

    seg_pred = {"segment_id": "seg_x_a", "last_frame_path": "assets/frames/seg_x_a_last.png"}
    seg = {
        "segment_id": "seg_a_b",
        "first_frame_source": "prev_last_frame",
        "pred_segment_id": "seg_x_a",
    }
    with patch("backend.app.services.first_frame.story_dir", return_value=root):
        dest = bind_prev_last_frame(monkeypatch_story, seg, {"seg_x_a": seg_pred})
    assert dest.exists()
    assert seg["first_frame_path"] == "assets/frames/seg_a_b_first.png"


def test_infer_produce_resume_status_prompts_after_frames() -> None:
    blueprint = {
        "characters": [{"status": "ready"}],
        "scenes": [{"status": "ready"}],
        "nodes": [{"shot_prompt_status": "pending"}],
        "segments": [
            {
                "produce_tier": "prefetch",
                "first_frame_source": "synthetic",
                "first_frame_path": "assets/frames/seg_first.png",
                "video_status": "pending",
            }
        ],
    }
    assert _infer_produce_resume_status(blueprint) == ProduceStatus.prompts


def test_infer_produce_resume_status_frames_not_prompts() -> None:
    blueprint = {
        "characters": [{"status": "ready"}],
        "scenes": [{"status": "ready"}],
        "nodes": [{"shot_prompt_status": "ready"}],
        "segments": [
            {
                "produce_tier": "prefetch",
                "first_frame_source": "synthetic",
                "first_frame_path": None,
                "video_status": "pending",
            }
        ],
    }
    assert _infer_produce_resume_status(blueprint) == ProduceStatus.frames


def test_infer_produce_resume_status_awaiting_when_only_chain_pending() -> None:
    blueprint = {
        "characters": [{"status": "ready"}],
        "scenes": [{"status": "ready"}],
        "nodes": [{"shot_prompt_status": "ready"}],
        "segments": [
            {
                "produce_tier": "prefetch",
                "first_frame_source": "synthetic",
                "first_frame_path": "assets/frames/seg_a_first.png",
                "video_status": "pending",
            },
            {
                "produce_tier": "prefetch",
                "first_frame_source": "prev_last_frame",
                "first_frame_path": None,
                "video_status": "pending",
            },
        ],
    }
    assert _infer_produce_resume_status(blueprint) == ProduceStatus.awaiting_video


def test_infer_produce_resume_status_videos_when_frames_done() -> None:
    blueprint = {
        "characters": [{"status": "ready"}],
        "scenes": [{"status": "ready"}],
        "nodes": [{"shot_prompt_status": "ready"}],
        "segments": [
            {
                "produce_tier": "prefetch",
                "first_frame_source": "synthetic",
                "first_frame_path": "assets/frames/seg_first.png",
                "video_status": "pending",
            }
        ],
    }
    assert _infer_produce_resume_status(blueprint) == ProduceStatus.awaiting_video


def test_infer_produce_resume_status_awaiting_video() -> None:
    blueprint = {
        "characters": [{"status": "ready"}],
        "scenes": [{"status": "ready"}],
        "nodes": [{"shot_prompt_status": "ready"}],
        "segments": [
            {
                "produce_tier": "prefetch",
                "first_frame_source": "synthetic",
                "first_frame_path": "assets/frames/seg_first.png",
                "video_status": "pending",
            }
        ],
    }
    assert _infer_produce_resume_status(blueprint) == ProduceStatus.awaiting_video


@pytest.mark.asyncio
async def test_produce_resume_from_paused(produce_story: str) -> None:
    await init_db()
    repo = StoryRepository()
    meta = repo.load_meta(produce_story)
    meta.produce_status = ProduceStatus.paused
    meta.produce_paused_from = ProduceStatus.prompts.value
    repo.save_meta(meta)

    svc = ProduceService(repo)
    with patch(
        "backend.app.services.produce_service.run_produce_static_graph",
        new=AsyncMock(return_value={}),
    ), patch(
        "backend.app.services.produce_service.run_first_frames_phase",
        new=AsyncMock(return_value={"ok": True}),
    ), patch(
        "backend.app.services.produce_service.enter_awaiting_video",
    ) as enter_await:
        result = await svc.run_produce(produce_story)
    assert result["stage"] == "awaiting_video"
    enter_await.assert_called_once()
    meta2 = repo.load_meta(produce_story)
    assert meta2.produce_paused_from is None


@pytest.mark.asyncio
async def test_produce_video_only_from_awaiting(produce_story: str) -> None:
    await init_db()
    repo = StoryRepository()
    meta = repo.load_meta(produce_story)
    meta.produce_status = ProduceStatus.awaiting_video
    repo.save_meta(meta)
    blueprint = load_blueprint(produce_story)
    blueprint["produce_status"] = ProduceStatus.awaiting_video.value
    save_blueprint(produce_story, blueprint)

    svc = ProduceService(repo)
    with patch(
        "backend.app.services.produce_service.run_video_generation",
        new=AsyncMock(return_value={"ok": True}),
    ), patch(
        "backend.app.services.produce_service.run_qc_loop",
        new=AsyncMock(return_value={"ok": True}),
    ):
        result = await svc.run_produce(produce_story, video_only=True)
    assert result["stage"] == "done"
