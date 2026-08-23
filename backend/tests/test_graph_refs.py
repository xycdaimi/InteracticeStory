from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode
from backend.app.services.graph_refs import (
    expandable_node_ids,
    mainline_node_ids,
    mainline_spine_complete,
    open_plot_leaf_ids,
    spine_path_from_root,
)


def test_expandable_and_leaf_indices_stable() -> None:
    g = StoryGraph(
        story_id="s1",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "z": StoryNode(id="z", kind=NodeKind.main, title="末", parent_id="n_root"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="支", parent_id="n_root"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="z"),
            StoryEdge(id="e2", source="n_root", target="a"),
        ],
    )
    assert expandable_node_ids(g) == ["a", "n_root", "z"]
    assert mainline_node_ids(g) == ["n_root", "z"]
    assert open_plot_leaf_ids(g) == ["a", "z"]


def test_spine_path_and_mainline_complete() -> None:
    g = StoryGraph(
        story_id="s1",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "m": StoryNode(id="m", kind=NodeKind.main, title="中", parent_id="n_root"),
            "e": StoryNode(
                id="e", kind=NodeKind.ending, title="终", parent_id="m", outcome="completed"
            ),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="m"),
            StoryEdge(id="e2", source="m", target="e"),
        ],
    )
    assert spine_path_from_root(g) == ["n_root", "m", "e"]
    assert mainline_spine_complete(g) is True
