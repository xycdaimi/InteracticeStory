from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.agents.fission_tools import FissionTools
from backend.app.config import get_settings
from backend.app.infrastructure.db import reset_engine_for_tests
from backend.app.models.enums import NodeKind
from backend.app.services.story_repository import StoryRepository


@pytest.fixture()
def story_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MIN_STORY_LINES", "5")
    get_settings.cache_clear()
    reset_engine_for_tests()
    yield tmp_path
    get_settings.cache_clear()
    reset_engine_for_tests()


def _script(
    state_in: str = "进入",
    state_out: str = "离开",
    line: str = "说一句",
) -> dict:
    return {
        "duration_seconds": 8,
        "dramatic_state_in": state_in,
        "dramatic_state_out": state_out,
        "beats": [
            {
                "t_start": 0,
                "t_end": 3,
                "shot": "中景",
                "action": "推进",
                "dialogue": [{"speaker": "角色", "line": line}],
            },
            {
                "t_start": 3,
                "t_end": 6,
                "shot": "近景",
                "action": "反应",
                "dialogue": [{"speaker": "角色", "line": "继续"}],
            },
        ],
        "visual_plan": {
            "first_frame": {
                "required": True,
                "depicts": "场面建立",
                "covers_character_ids": [],
            },
            "character_refs": [],
            "scene_ref": None,
            "hidden_or_pov_only_ids": [],
        },
    }


def test_define_spine_apply_tree_write_scripts(story_env: Path):
    repo = StoryRepository()
    sid = repo.create_story(inspiration="实验室悬疑测试")
    tools = FissionTools(sid, repo=repo)

    spine = json.loads(
        tools.define_story_spine(
            protagonist="林可",
            completion_point="揭开真相",
            key_events=[
                "接到匿名信",
                "潜入实验室",
                "发现异常数据",
                "对质导师",
                "拿到关键样本",
                "揭开真相",
            ],
        )
    )
    assert spine.get("ok") is True

    tree = {
        "root": "S01",
        "nodes": [
            {
                "id": "S01",
                "type": "start",
                "title": "起点",
                "summary": "接到线索",
                "spine_event": "接到匿名信",
                "option_label": "继续",
                "parent": None,
            },
            {
                "id": "S02",
                "type": "branch",
                "title": "潜入",
                "summary": "潜入实验室",
                "parent": "S01",
                "option_label": "「今晚就进实验室」",
                "spine_event": "潜入实验室",
            },
            {
                "id": "E1",
                "type": "ending",
                "title": "真相大白",
                "summary": "揭开真相",
                "parent": "S02",
                "option_label": "「证据够了」",
                "outcome": "completed",
            },
        ],
        "edges": [
            {"from": "S01", "to": "S02", "label": "「今晚就进实验室」"},
            {"from": "S02", "to": "E1", "label": "「证据够了」"},
        ],
    }
    applied = json.loads(tools.apply_plot_tree(tree))
    assert applied.get("ok") is True
    id_map = applied["id_map"]
    g = repo.load_graph(sid)
    assert g.root_id in g.nodes
    assert all(n.script is None for nid, n in g.nodes.items() if nid != g.root_id)

    s02 = id_map["S02"]
    written = json.loads(
        tools.write_node_scripts(
            [
                {
                    "node_id": s02,
                    "script": _script("接到线索", "潜入成功", "「今晚就进实验室」"),
                    "title": "潜入",
                    "summary": "潜入实验室",
                }
            ]
        )
    )
    assert written.get("ok") is True
    g2 = repo.load_graph(sid)
    assert g2.nodes[s02].script is not None
    assert g2.nodes[s02].kind in (NodeKind.main, NodeKind.branch)
