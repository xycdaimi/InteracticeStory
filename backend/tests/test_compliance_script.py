from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import PlotLine, StoryGraph, StoryNode
from backend.app.services.compliance import path_text_for_line


def test_path_text_includes_missing_script_marker() -> None:
    g = StoryGraph(
        story_id="s1",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(
                id="n_root", kind=NodeKind.root, title="起", summary="s"
            ),
            "n_a": StoryNode(
                id="n_a", kind=NodeKind.main, title="A", summary="大纲"
            ),
        },
        edges=[],
        options=[],
    )
    text = path_text_for_line(
        g, PlotLine(line_id="pl_1", node_path=["n_root", "n_a"], ending_id="n_a")
    )
    assert "script: <缺失>" in text
