from __future__ import annotations

from backend.app.config import Settings
from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode, StoryOption


def test_leaf_line_count_after_fork() -> None:
    g = StoryGraph(
        story_id="s1",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起盘"),
            "n1": StoryNode(id="n1", kind=NodeKind.main, title="主1", parent_id="n_root"),
            "n2a": StoryNode(id="n2a", kind=NodeKind.branch, title="支A", parent_id="n1"),
            "n2b": StoryNode(id="n2b", kind=NodeKind.branch, title="支B", parent_id="n1"),
            "n2c": StoryNode(id="n2c", kind=NodeKind.branch, title="支C", parent_id="n1"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="n1"),
            StoryEdge(id="e2", source="n1", target="n2a"),
            StoryEdge(id="e3", source="n1", target="n2b"),
            StoryEdge(id="e4", source="n1", target="n2c"),
        ],
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="n1", label="开始"),
            StoryOption(id="o2", from_node_id="n1", to_node_id="n2a", label="A"),
            StoryOption(id="o3", from_node_id="n1", to_node_id="n2b", label="B"),
            StoryOption(id="o4", from_node_id="n1", to_node_id="n2c", label="C"),
        ],
    )
    assert g.line_count == 3
    assert set(g.leaf_ids()) == {"n2a", "n2b", "n2c"}
    assert g.can_converge(min_lines=30) is False
    assert g.can_converge(min_lines=3) is False  # 浅层分叉，深度未达标


def test_single_chain_line_count_one() -> None:
    g = StoryGraph(
        story_id="s2",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起盘"),
            "n1": StoryNode(id="n1", kind=NodeKind.main, title="主1", parent_id="n_root"),
            "n2": StoryNode(id="n2", kind=NodeKind.main, title="主2", parent_id="n1"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="n1"),
            StoryEdge(id="e2", source="n1", target="n2"),
        ],
    )
    assert g.line_count == 1
    assert g.leaf_ids() == ["n2"]


def test_shared_ending_inbound_counts_as_plot_lines() -> None:
    g = StoryGraph(
        story_id="s3",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起盘"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="线A", parent_id="n_root"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="线B", parent_id="n_root"),
            "c": StoryNode(id="c", kind=NodeKind.branch, title="线C", parent_id="n_root"),
            "end": StoryNode(id="end", kind=NodeKind.ending, title="共用结局", parent_id="a"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="n_root", target="b"),
            StoryEdge(id="e3", source="n_root", target="c"),
            StoryEdge(id="e4", source="a", target="end"),
            StoryEdge(id="e5", source="b", target="end"),
            StoryEdge(id="e6", source="c", target="end"),
        ],
    )
    assert g.ending_count() == 1
    assert g.line_count == 3
    assert g.can_converge(min_lines=3) is False  # 路径深度未达 required_path_depth


def test_min_story_lines_setting_default() -> None:
    assert Settings.model_fields["min_story_lines"].default == 8
