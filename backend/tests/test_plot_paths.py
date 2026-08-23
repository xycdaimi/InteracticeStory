from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode
from backend.app.services.plot_paths import (
    enumerate_plot_paths,
    open_plot_path_count,
    root_to_ending_path_count,
)
from backend.app.services.script_sanitize import sanitize_script_dict


def test_merged_paths_count_as_multiple_lines() -> None:
    """两条分叉后汇合到同一叶：应计 2 条路径而非 1 个叶。"""
    g = StoryGraph(
        story_id="s_dag",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="线A", parent_id="n_root"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="线B", parent_id="n_root"),
            "hub": StoryNode(id="hub", kind=NodeKind.main, title="汇合点", parent_id="a"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="n_root", target="b"),
            StoryEdge(id="e3", source="a", target="hub"),
            StoryEdge(id="e4", source="b", target="hub"),
        ],
    )
    assert len(g.leaf_ids()) == 1
    assert open_plot_path_count(g) == 2
    assert root_to_ending_path_count(g) == 0
    assert g.line_count == 0


def test_mainline_ending_plus_branches_count_all_paths() -> None:
    """主线已有结局时，新分支路径须计入 plot_path_count，不能一直停在 1。"""
    g = StoryGraph(
        story_id="s_ml",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "m1": StoryNode(id="m1", kind=NodeKind.main, title="主线1", parent_id="n_root"),
            "end": StoryNode(
                id="end",
                kind=NodeKind.ending,
                title="主线结局",
                parent_id="m1",
                outcome="completed",
            ),
            "b1": StoryNode(id="b1", kind=NodeKind.branch, title="支1", parent_id="m1"),
            "b2": StoryNode(id="b2", kind=NodeKind.branch, title="支2", parent_id="m1"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="m1"),
            StoryEdge(id="e2", source="m1", target="end"),
            StoryEdge(id="e3", source="m1", target="b1"),
            StoryEdge(id="e4", source="m1", target="b2"),
        ],
    )
    assert open_plot_path_count(g) == 3
    assert root_to_ending_path_count(g) == 1
    assert g.line_count == 1
    paths = enumerate_plot_paths(g)
    assert len(paths) == 1
    assert {tuple(p) for p in paths} == {
        ("n_root", "m1", "end"),
    }


def test_sanitize_strips_overlap_and_string_refs() -> None:
    raw = {
        "duration_seconds": 8,
        "dramatic_state_in": "x",
        "dramatic_state_out": "y",
        "beats": [
            {"t_start": 0, "t_end": 4, "dialogue": [{"speaker": "A", "line": "hi"}]},
            {"t_start": 4, "t_end": 8, "dialogue": [{"speaker": "B", "line": "ok"}]},
        ],
        "visual_plan": {
            "first_frame": {
                "required": True,
                "depicts": "敌将",
                "covers_character_ids": ["c_enemy"],
            },
            "character_refs": ["c_enemy", {"character_id": "c_other"}],
        },
    }
    fixed = sanitize_script_dict(raw)
    refs = fixed["visual_plan"]["character_refs"]
    assert refs == [{"character_id": "c_other"}]
