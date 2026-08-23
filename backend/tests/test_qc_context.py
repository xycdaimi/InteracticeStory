from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.infrastructure.db import reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, shot_prompt_path, story_dir
from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph, StoryNode
from backend.app.services.qc_context import build_segment_qc_context
from backend.app.services.story_repository import StoryRepository


@pytest.fixture
def qc_story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_engine_for_tests()
    repo = StoryRepository()
    sid = repo.create_story("QC 测试")
    story_dir(sid).mkdir(parents=True, exist_ok=True)
    graph = StoryGraph(
        story_id=sid,
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(
                id="n_a",
                kind=NodeKind.main,
                title="挑战",
                summary="主角出阵",
                scene_id="s_1",
                character_ids=["c_1"],
            ),
        },
        edges=[],
        options=[],
    )
    repo.save_graph(graph)
    blueprint = {
        "story_id": sid,
        "characters": [
            {
                "character_id": "c_1",
                "name": "主角",
                "appearance_prompt": "青袍",
            }
        ],
        "scenes": [
            {"scene_id": "s_1", "name": "关前", "visual_prompt": "关隘前空地"}
        ],
        "nodes": [
            {
                "node_id": "n_a",
                "title": "挑战",
                "summary": "主角出阵",
                "scene_id": "s_1",
                "character_ids": ["c_1"],
            }
        ],
        "segments": [
            {
                "segment_id": "seg_n_root_n_a",
                "prompt_node_id": "n_a",
            }
        ],
    }
    blueprint_path(sid).write_text(json.dumps(blueprint), encoding="utf-8")
    shot_prompt_path(sid, "n_a").parent.mkdir(parents=True, exist_ok=True)
    shot_prompt_path(sid, "n_a").write_text(
        json.dumps({"prompt_text": "【场景】关前【台词】主角：『来战』"}),
        encoding="utf-8",
    )
    return sid


def test_build_segment_qc_context(qc_story: str) -> None:
    repo = StoryRepository()
    blueprint = json.loads(blueprint_path(qc_story).read_text(encoding="utf-8"))
    segment = blueprint["segments"][0]
    ctx = build_segment_qc_context(qc_story, segment, repo=repo)
    assert "挑战" in ctx
    assert "主角出阵" in ctx
    assert "【分镜剧本】" in ctx
    assert "来战" in ctx
    assert "【审查范围】仅判断上述单段视频内部是否合理。" in ctx
