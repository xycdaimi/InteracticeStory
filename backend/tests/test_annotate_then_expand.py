from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, compliance_path
from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import PlotLine, StoryGraph, StoryNode
from backend.app.services.asset_pipeline import sync_segments_to_blueprint
from backend.app.services.segment_plan import expand_segments
from backend.app.services.shot_continuity import annotate_shot_continuity
from backend.app.services.story_repository import StoryRepository


@pytest.mark.asyncio
async def test_annotate_then_expand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_engine_for_tests()
    await init_db()
    repo = StoryRepository()
    sid = repo.create_story("全链路")
    graph = StoryGraph(
        story_id=sid,
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起", scene_id="s1"),
            "n_a": StoryNode(
                id="n_a",
                kind=NodeKind.main,
                title="A",
                summary="甲行动",
                scene_id="s1",
            ),
            "n_b": StoryNode(
                id="n_b",
                kind=NodeKind.main,
                title="B",
                summary="乙回应",
                scene_id="s1",
            ),
        },
        edges=[],
        options=[],
    )
    repo.save_graph(graph)
    lines = [PlotLine(line_id="pl1", node_path=["n_root", "n_a", "n_b"], ending_id="n_b")]
    compliance_path(sid).write_text(
        json.dumps({"kept_lines": [lines[0].model_dump()]}),
        encoding="utf-8",
    )
    blueprint_path(sid).write_text(
        json.dumps({"story_id": sid, "segments": [], "characters": [], "scenes": []}),
        encoding="utf-8",
    )

    mock_chat = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "edges": [
                                    {
                                        "from_node_id": "n_a",
                                        "to_node_id": "n_b",
                                        "continues": True,
                                        "reason": "连续",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
    )
    with patch("backend.app.services.shot_continuity.GeekAIClient") as mock_cls:
        mock_cls.return_value.chat = mock_chat
        mock_cls.return_value.aclose = AsyncMock()
        count = await sync_segments_to_blueprint(sid, repo)

    assert count == 2
    blueprint = json.loads(blueprint_path(sid).read_text(encoding="utf-8"))
    segs = {s["segment_id"]: s for s in blueprint["segments"]}
    assert segs["seg_n_a_n_b"]["continues_from_prev_shot"] is True
    assert segs["seg_n_a_n_b"]["first_frame_source"] == "prev_last_frame"
    assert segs["seg_n_root_n_a"]["first_frame_source"] == "synthetic"

    fresh = expand_segments(graph, lines)
    assert all(s["first_frame_source"] == "synthetic" for s in fresh)
