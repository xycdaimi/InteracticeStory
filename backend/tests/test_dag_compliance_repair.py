from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode, StoryOption
from backend.app.services.dag_compliance_repair import remove_branch_edge
from backend.app.services.plot_paths import root_to_ending_path_count


def test_remove_branch_edge_does_not_drop_nodes() -> None:
    g = StoryGraph(
        story_id="s",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="A"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="B"),
            "e": StoryNode(
                id="e",
                kind=NodeKind.ending,
                title="结",
                outcome="completed",
            ),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="n_root", target="b"),
            StoryEdge(id="e3", source="a", target="e"),
            StoryEdge(id="e4", source="b", target="e"),
        ],
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="a", label="A"),
            StoryOption(id="o2", from_node_id="n_root", to_node_id="b", label="B"),
            StoryOption(id="o3", from_node_id="a", to_node_id="e", label="结"),
            StoryOption(id="o4", from_node_id="b", to_node_id="e", label="结"),
        ],
    )
    assert root_to_ending_path_count(g) == 2
    remove_branch_edge(g, "n_root", "b")
    assert root_to_ending_path_count(g) == 1
    assert "b" in g.nodes
    assert "e" in g.nodes
