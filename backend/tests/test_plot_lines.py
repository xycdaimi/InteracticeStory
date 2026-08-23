from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode


def test_iter_plot_lines_shared_ending() -> None:
    """root→A→E1 与 root→B→E1 应得到 2 条线，共享同一 ending。"""
    g = StoryGraph(
        story_id="s_pl",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起盘"),
            "a": StoryNode(id="a", kind=NodeKind.branch, title="线A", parent_id="n_root"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="线B", parent_id="n_root"),
            "e1": StoryNode(
                id="e1",
                kind=NodeKind.ending,
                title="共用结局",
                parent_id="a",
                share_key="ok",
                outcome="completed",
            ),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="n_root", target="b"),
            StoryEdge(id="e3", source="a", target="e1"),
            StoryEdge(id="e4", source="b", target="e1"),
        ],
    )
    lines = g.iter_plot_lines()
    assert len(lines) == 2
    assert g.line_count == 2
    assert {tuple(pl.node_path) for pl in lines} == {
        ("n_root", "a", "e1"),
        ("n_root", "b", "e1"),
    }
    assert all(pl.ending_id == "e1" for pl in lines)
    assert all(pl.outcome == "completed" for pl in lines)
    assert all(pl.share_key == "ok" for pl in lines)
    assert lines[0].line_id == "pl_0001"
    assert lines[1].line_id == "pl_0002"


def test_old_node_json_defaults_compatible() -> None:
    """旧 graph 节点缺新字段时应可解析。"""
    node = StoryNode.model_validate(
        {"id": "n1", "kind": "main", "title": "旧节点", "summary": "x", "parent_id": "n_root"}
    )
    assert node.character_ids == []
    assert node.scene_id is None
    assert node.share_key is None
    assert node.outcome is None
