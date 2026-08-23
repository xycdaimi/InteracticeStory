from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode, StoryOption
from backend.app.services.dag_outline import export_dag_outline


def test_export_dag_outline_no_script() -> None:
    g = StoryGraph(
        story_id="s",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="岔路A", summary="大纲A"),
            "e": StoryNode(
                id="e",
                kind=NodeKind.ending,
                title="结局",
                summary="收束",
                outcome="completed",
            ),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="a", target="e"),
        ],
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="a", label="「走A」"),
            StoryOption(id="o2", from_node_id="a", to_node_id="e", label="「结束」"),
        ],
    )
    outline = export_dag_outline(g)
    assert outline["root_id"] == "n_root"
    assert outline["plot_line_count"] == 1
    assert len(outline["nodes"]) == 3
    assert len(outline["choices"]) == 2
    blob = str(outline)
    assert "dramatic_state" not in blob
    assert "beats" not in blob
    assert outline["nodes"][1]["title"] == "岔路A"
