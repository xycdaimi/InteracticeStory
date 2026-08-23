from __future__ import annotations

from collections import Counter

from backend.app.models.enums import ComplianceStatus, NodeKind
from backend.app.models.story_graph import PlotLine, StoryGraph


def prune_rejected_lines(
    graph: StoryGraph,
    lines: list[PlotLine],
) -> tuple[StoryGraph, list[PlotLine]]:
    """
    按合格线引用计数剪枝：删除仅被拒线使用的非 root 节点及其边/选项。
    不回头裂变。若无合格线，图不改，返回空 kept 列表由调用方标 failed。
    """
    kept = [pl for pl in lines if pl.compliance_status == ComplianceStatus.passed.value]
    if not kept:
        return graph, kept

    ref: Counter[str] = Counter()
    for pl in kept:
        for nid in pl.node_path:
            ref[nid] += 1

    drop = {
        nid
        for nid, node in graph.nodes.items()
        if ref[nid] == 0 and nid != graph.root_id and node.kind != NodeKind.root
    }
    if not drop:
        return graph, kept

    graph.nodes = {nid: n for nid, n in graph.nodes.items() if nid not in drop}
    graph.edges = [
        e for e in graph.edges if e.source not in drop and e.target not in drop
    ]
    graph.options = [
        o
        for o in graph.options
        if o.from_node_id not in drop and o.to_node_id not in drop
    ]
    return graph, kept
