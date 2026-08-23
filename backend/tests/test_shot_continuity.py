from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import PlotLine, StoryGraph, StoryNode, StoryOption
from backend.app.services.segment_plan import expand_segments
from backend.app.services.shot_continuity import (
    annotate_shot_continuity,
    apply_hard_rules,
    build_shot_continuity_user,
    continuity_cache_path,
    load_continuity_cache,
    parse_shot_continuity_response,
    save_continuity_cache,
)


def _graph_same_scene() -> StoryGraph:
    return StoryGraph(
        story_id="s1",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起", scene_id="s1"),
            "n_a": StoryNode(
                id="n_a",
                kind=NodeKind.main,
                title="对白",
                summary="甲说话",
                scene_id="s1",
            ),
            "n_b": StoryNode(
                id="n_b",
                kind=NodeKind.main,
                title="回应",
                summary="乙回答",
                scene_id="s1",
            ),
        },
        edges=[],
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="n_a", label="开口"),
            StoryOption(id="o2", from_node_id="n_a", to_node_id="n_b", label="追问"),
        ],
    )


def _graph_cross_scene() -> StoryGraph:
    return StoryGraph(
        story_id="s2",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起", scene_id="s1"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="室内", scene_id="s1"),
            "n_b": StoryNode(id="n_b", kind=NodeKind.main, title="室外", scene_id="s2"),
        },
        edges=[],
        options=[],
    )


def test_hard_rule_root() -> None:
    graph = _graph_same_scene()
    seg = {
        "from_node_id": "n_root",
        "to_node_id": "n_a",
        "from_is_root": True,
        "pred_candidate_ids": [],
        "pred_segment_id": None,
    }
    blocked, code = apply_hard_rules(seg, graph, {})
    assert blocked is True
    assert code == "ROOT_EDGE"


def test_hard_rule_multi_pred() -> None:
    graph = _graph_same_scene()
    seg = {
        "from_node_id": "n_a",
        "to_node_id": "n_b",
        "pred_candidate_ids": ["seg_x", "seg_y"],
        "pred_segment_id": None,
    }
    blocked, code = apply_hard_rules(seg, graph, {})
    assert blocked is True
    assert code == "MULTI_PRED"


def test_hard_rule_cross_scene() -> None:
    graph = _graph_cross_scene()
    lines = [
        PlotLine(line_id="pl1", node_path=["n_root", "n_a", "n_b"], ending_id="n_b"),
    ]
    segs = expand_segments(graph, lines)
    seg = next(s for s in segs if s["from_node_id"] == "n_a")
    blocked, code = apply_hard_rules(seg, graph, {s["segment_id"]: s for s in segs})
    assert blocked is True
    assert code == "CROSS_SCENE"


def test_parse_response() -> None:
    raw = json.dumps(
        {
            "edges": [
                {
                    "from_node_id": "n_a",
                    "to_node_id": "n_b",
                    "continues": True,
                    "reason": "连续对白",
                }
            ]
        }
    )
    parsed = parse_shot_continuity_response(raw)
    assert parsed[("n_a", "n_b")] == (True, "连续对白")


def test_lookup_llm_segment_id_mistake() -> None:
    from backend.app.services.shot_continuity import EdgeContinuityInput, lookup_llm_edge_result

    edge = EdgeContinuityInput(
        segment_id="seg_n_a_n_b",
        from_node_id="n_a",
        to_node_id="n_b",
        pred_segment_id="seg_n_root_n_a",
        option_label="",
        from_title="",
        from_summary="",
        to_title="",
        to_summary="",
    )
    parsed = {
        ("seg_n_root_n_a", "seg_n_a_n_b"): (True, "连续"),
    }
    assert lookup_llm_edge_result(parsed, edge) == (True, "连续")


@pytest.fixture
def mock_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services import shot_continuity as sc

    monkeypatch.setattr(
        sc.StoryRepository,
        "load_meta",
        lambda self, sid: type("M", (), {"inspiration": "测试"})(),
    )


@pytest.mark.asyncio
async def test_llm_true_same_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_meta: None
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    graph = _graph_same_scene()
    lines = [PlotLine(line_id="pl1", node_path=["n_root", "n_a", "n_b"], ending_id="n_b")]
    segs = expand_segments(graph, lines)
    seg_ab = next(s for s in segs if s["to_node_id"] == "n_b")

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
                                        "reason": "连续对白",
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
        out = await annotate_shot_continuity("story1", graph, lines, segs)
    by_id = {s["segment_id"]: s for s in out}
    assert by_id[seg_ab["segment_id"]]["continues_from_prev_shot"] is True
    assert by_id[seg_ab["segment_id"]]["first_frame_source"] == "prev_last_frame"


@pytest.mark.asyncio
async def test_llm_false_same_scene_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_meta: None
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    graph = _graph_same_scene()
    lines = [PlotLine(line_id="pl1", node_path=["n_root", "n_a", "n_b"], ending_id="n_b")]
    segs = expand_segments(graph, lines)
    seg_ab = next(s for s in segs if s["to_node_id"] == "n_b")

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
                                        "continues": False,
                                        "reason": "切镜",
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
        out = await annotate_shot_continuity("story2", graph, lines, segs)
    by_id = {s["segment_id"]: s for s in out}
    assert by_id[seg_ab["segment_id"]]["continues_from_prev_shot"] is False
    assert by_id[seg_ab["segment_id"]]["first_frame_source"] == "synthetic"


@pytest.mark.asyncio
async def test_cache_skips_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    graph = _graph_same_scene()
    lines = [PlotLine(line_id="pl1", node_path=["n_root", "n_a", "n_b"], ending_id="n_b")]
    segs = expand_segments(graph, lines)
    seg_ab = next(s for s in segs if s["to_node_id"] == "n_b")
    from backend.app.services.shot_continuity import graph_revision

    rev = graph_revision(graph)
    save_continuity_cache(
        "story3",
        {
            "version": 1,
            "graph_revision": rev,
            "edges": {"n_a|n_b": {"continues": True, "reason": "cached"}},
        },
    )
    assert continuity_cache_path("story3").is_file()

    mock_chat = AsyncMock()
    with patch("backend.app.services.shot_continuity.GeekAIClient") as mock_cls:
        mock_cls.return_value.chat = mock_chat
        mock_cls.return_value.aclose = AsyncMock()
        out = await annotate_shot_continuity("story3", graph, lines, segs)
    mock_chat.assert_not_called()
    by_id = {s["segment_id"]: s for s in out}
    assert by_id[seg_ab["segment_id"]]["continues_from_prev_shot"] is True
    assert "CACHE" in (by_id[seg_ab["segment_id"]]["continuity_reason"] or "")


def test_build_user_no_scene_names() -> None:
    from backend.app.services.shot_continuity import EdgeContinuityInput

    edges = [
        EdgeContinuityInput(
            segment_id="seg_n_a_n_b",
            from_node_id="n_a",
            to_node_id="n_b",
            pred_segment_id="seg_n_root_n_a",
            option_label="追问",
            from_title="对白",
            from_summary="甲说话",
            to_title="回应",
            to_summary="乙回答",
        )
    ]
    text = build_shot_continuity_user("灵感", edges)
    assert "scene" not in text.lower()
    assert "场景" not in text
    assert "追问" in text
