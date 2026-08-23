from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode
from backend.app.services.plot_paths import open_plot_path_count


def test_open_plot_path_count_simple_fork() -> None:
    g = StoryGraph(
        story_id="s",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="A", parent_id="n_root"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="B", parent_id="n_root"),
            "e1": StoryNode(id="e1", kind=NodeKind.ending, title="E1", parent_id="a"),
            "e2": StoryNode(id="e2", kind=NodeKind.ending, title="E2", parent_id="b"),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="n_root", target="b"),
            StoryEdge(id="e3", source="a", target="e1"),
            StoryEdge(id="e4", source="b", target="e2"),
        ],
        options=[],
    )
    assert open_plot_path_count(g) == 2
    assert g.line_count == 2
