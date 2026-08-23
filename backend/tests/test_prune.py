from __future__ import annotations

from backend.app.models.enums import ComplianceStatus, NodeKind
from backend.app.models.story_graph import PlotLine, StoryEdge, StoryGraph, StoryNode, StoryOption
from backend.app.services.prune import prune_rejected_lines


def _shared_prefix_fixture() -> tuple[StoryGraph, list[PlotLine]]:
    """root→A→B→E_ok 与 root→A→C→E_bad；拒 C 线后 A 应保留、C 应消失。"""
    g = StoryGraph(
        story_id="prune_demo",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "a": StoryNode(id="a", kind=NodeKind.main, title="共享", parent_id="n_root"),
            "b": StoryNode(id="b", kind=NodeKind.branch, title="合格支", parent_id="a"),
            "c": StoryNode(id="c", kind=NodeKind.branch, title="拒支", parent_id="a"),
            "e_ok": StoryNode(
                id="e_ok",
                kind=NodeKind.ending,
                title="好结局",
                parent_id="b",
                share_key="ok",
                outcome="completed",
            ),
            "e_bad": StoryNode(
                id="e_bad",
                kind=NodeKind.ending,
                title="坏结局",
                parent_id="c",
                share_key="bad",
                outcome="failed",
            ),
        },
        edges=[
            StoryEdge(id="e1", source="n_root", target="a"),
            StoryEdge(id="e2", source="a", target="b"),
            StoryEdge(id="e3", source="a", target="c"),
            StoryEdge(id="e4", source="b", target="e_ok"),
            StoryEdge(id="e5", source="c", target="e_bad"),
        ],
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="a", label="起"),
            StoryOption(id="o2", from_node_id="a", to_node_id="b", label="好"),
            StoryOption(id="o3", from_node_id="a", to_node_id="c", label="坏"),
            StoryOption(id="o4", from_node_id="b", to_node_id="e_ok", label="收好"),
            StoryOption(id="o5", from_node_id="c", to_node_id="e_bad", label="收坏"),
        ],
    )
    lines = [
        PlotLine(
            line_id="pl_0001",
            node_path=["n_root", "a", "b", "e_ok"],
            ending_id="e_ok",
            compliance_status=ComplianceStatus.passed.value,
        ),
        PlotLine(
            line_id="pl_0002",
            node_path=["n_root", "a", "c", "e_bad"],
            ending_id="e_bad",
            compliance_status=ComplianceStatus.rejected.value,
            reasons=["剧情拉垮: 空洞"],
        ),
    ]
    return g, lines


def test_prune_keeps_shared_drops_rejected_only() -> None:
    g, lines = _shared_prefix_fixture()
    g2, kept = prune_rejected_lines(g, lines)
    assert len(kept) == 1
    assert kept[0].line_id == "pl_0001"
    assert "a" in g2.nodes and "b" in g2.nodes and "e_ok" in g2.nodes
    assert "c" not in g2.nodes and "e_bad" not in g2.nodes
    assert g2.line_count == 1
    assert g2.ending_count() == 1


def test_prune_zero_kept_leaves_graph_untouched() -> None:
    g, lines = _shared_prefix_fixture()
    for pl in lines:
        pl.compliance_status = ComplianceStatus.rejected.value
        pl.reasons = ["离谱"]
    g2, kept = prune_rejected_lines(g, lines)
    assert kept == []
    assert set(g2.nodes) == set(g.nodes)
