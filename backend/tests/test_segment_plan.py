from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import PlotLine, StoryGraph, StoryNode
from backend.app.services.segment_plan import (
    annotate_prefetch_tiers,
    derive_first_frame_source,
    expand_segments,
    segment_id,
    topo_waves,
)


def _mini_graph() -> StoryGraph:
    graph = StoryGraph(
        story_id="s1",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起", scene_id="s1"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="A", scene_id="s1"),
            "n_b": StoryNode(id="n_b", kind=NodeKind.main, title="B", scene_id="s1"),
            "n_c": StoryNode(id="n_c", kind=NodeKind.main, title="C", scene_id="s2"),
            "n_e": StoryNode(id="n_e", kind=NodeKind.ending, title="E", scene_id="s2"),
        },
        edges=[],
        options=[],
    )
    return graph


def test_segment_id() -> None:
    assert segment_id("n_a", "n_b") == "seg_n_a_n_b"


def test_derive_first_frame_source() -> None:
    assert derive_first_frame_source({"from_is_root": True}) == "synthetic"
    assert (
        derive_first_frame_source(
            {
                "from_is_root": False,
                "pred_candidate_ids": ["a", "b"],
                "pred_segment_id": None,
                "continues_from_prev_shot": True,
            }
        )
        == "synthetic"
    )
    assert (
        derive_first_frame_source(
            {
                "from_is_root": False,
                "pred_candidate_ids": ["a"],
                "pred_segment_id": "a",
                "continues_from_prev_shot": True,
            }
        )
        == "prev_last_frame"
    )
    assert (
        derive_first_frame_source(
            {
                "from_is_root": False,
                "pred_candidate_ids": ["a"],
                "pred_segment_id": "a",
                "continues_from_prev_shot": False,
            }
        )
        == "synthetic"
    )


def test_topo_waves_chain_and_parallel() -> None:
    segments = [
        {"segment_id": "a", "first_frame_source": "synthetic"},
        {
            "segment_id": "b",
            "first_frame_source": "prev_last_frame",
            "pred_segment_id": "a",
        },
        {
            "segment_id": "c",
            "first_frame_source": "prev_last_frame",
            "pred_segment_id": "b",
        },
        {"segment_id": "x", "first_frame_source": "synthetic"},
    ]
    waves = topo_waves(segments)
    assert len(waves) == 3
    assert {s["segment_id"] for s in waves[0]} == {"a", "x"}
    assert [s["segment_id"] for s in waves[1]] == ["b"]
    assert [s["segment_id"] for s in waves[2]] == ["c"]


def test_annotate_prefetch_tiers_covers_mainline() -> None:
    graph = _mini_graph()
    lines = [
        PlotLine(
            line_id="pl_main",
            node_path=["n_root", "n_a", "n_b", "n_c", "n_e"],
            ending_id="n_e",
            outcome="completed",
        ),
        PlotLine(
            line_id="pl_long",
            node_path=["n_root", "n_a", "n_b", "n_c", "n_e"],
            ending_id="n_e",
            outcome="failed",
        ),
    ]
    segs = expand_segments(graph, lines[:1])
    annotate_prefetch_tiers(graph, lines[:1], segs, ratio=0.8)
    assert all(s.get("produce_tier") == "prefetch" for s in segs)


def test_annotate_prefetch_tiers_partial() -> None:
    graph = StoryGraph(
        story_id="s2",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起", scene_id="s1"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="A", scene_id="s1"),
            "n_b": StoryNode(id="n_b", kind=NodeKind.branch, title="B", scene_id="s2"),
            "n_c": StoryNode(id="n_c", kind=NodeKind.branch, title="C", scene_id="s2"),
            "n_e1": StoryNode(id="n_e1", kind=NodeKind.ending, title="E1", scene_id="s2"),
            "n_e2": StoryNode(id="n_e2", kind=NodeKind.ending, title="E2", scene_id="s2"),
        },
        edges=[],
        options=[],
    )
    lines = [
        PlotLine(
            line_id="pl_short",
            node_path=["n_root", "n_a", "n_e1"],
            ending_id="n_e1",
            outcome="completed",
        ),
        PlotLine(
            line_id="pl_long",
            node_path=["n_root", "n_a", "n_b", "n_c", "n_e2"],
            ending_id="n_e2",
            outcome="failed",
        ),
    ]
    segs = expand_segments(graph, lines)
    annotate_prefetch_tiers(graph, lines, segs, ratio=0.5)
    prefetch = [s for s in segs if s.get("produce_tier") == "prefetch"]
    on_demand = [s for s in segs if s.get("produce_tier") == "on_demand"]
    assert len(prefetch) >= 1
    assert len(on_demand) >= 1
    assert len(prefetch) + len(on_demand) == len(segs)


def test_expand_segments_dedup_and_defaults() -> None:
    graph = _mini_graph()
    lines = [
        PlotLine(
            line_id="pl_0001",
            node_path=["n_root", "n_a", "n_b", "n_c", "n_e"],
            ending_id="n_e",
        )
    ]
    segs = expand_segments(graph, lines)
    by_id = {s["segment_id"]: s for s in segs}
    assert len(segs) == 4
    for seg in segs:
        assert seg["first_frame_source"] == "synthetic"
        assert seg["continues_from_prev_shot"] is False
        assert "continuity_group" not in seg
    assert by_id["seg_n_a_n_b"]["pred_segment_id"] == "seg_n_root_n_a"
    assert by_id["seg_n_a_n_b"]["pred_candidate_ids"] == ["seg_n_root_n_a"]


def test_expand_segments_uses_from_node_when_ending_has_no_script() -> None:
    from backend.app.models.story_graph import NodeScript

    script = NodeScript.model_validate(
        {
            "duration_seconds": 8,
            "dramatic_state_in": "in",
            "dramatic_state_out": "out",
            "beats": [
                {
                    "t_start": 0,
                    "t_end": 4,
                    "dialogue": [{"speaker": "甲", "line": "走"}],
                },
                {
                    "t_start": 4,
                    "t_end": 8,
                    "dialogue": [{"speaker": "甲", "line": "停"}],
                },
            ],
            "visual_plan": {
                "first_frame": {"required": False, "depicts": "x"},
                "character_refs": [],
            },
        }
    )
    graph = StoryGraph(
        story_id="s1",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_leaf": StoryNode(
                id="n_leaf", kind=NodeKind.branch, title="叶", script=script
            ),
            "n_end": StoryNode(id="n_end", kind=NodeKind.ending, title="结局"),
        },
        edges=[],
        options=[],
    )
    lines = [
        PlotLine(
            line_id="pl_1",
            node_path=["n_root", "n_leaf", "n_end"],
            ending_id="n_end",
        )
    ]
    seg = expand_segments(graph, lines)[0]
    assert seg["prompt_node_id"] == "n_leaf"


def test_prefetch_frame_stats_splits_synthetic_and_chain() -> None:
    from backend.app.services.segment_plan import prefetch_frame_stats

    segments = [
        {
            "produce_tier": "prefetch",
            "first_frame_source": "synthetic",
            "first_frame_path": "a.png",
        },
        {
            "produce_tier": "prefetch",
            "first_frame_source": "synthetic",
            "first_frame_path": None,
        },
        {
            "produce_tier": "prefetch",
            "first_frame_source": "prev_last_frame",
            "first_frame_path": None,
        },
        {"produce_tier": "on_demand", "first_frame_source": "synthetic"},
    ]
    stats = prefetch_frame_stats(segments)
    assert stats["synthetic_frames"] == {"total": 2, "ready": 1}
    assert stats["chain_frames"] == {"total": 1, "ready": 0}
