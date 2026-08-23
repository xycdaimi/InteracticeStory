from __future__ import annotations

from collections import defaultdict

from backend.app.models.story_graph import StoryGraph


def apply_layout(graph: StoryGraph, x_gap: float = 280.0, y_gap: float = 160.0) -> None:
    """按 DAG 最长路径分层布局，汇合节点取 max(父层)+1，避免多路径重复 walk 导致坐标错乱。"""
    root = graph.root_id
    if root not in graph.nodes:
        return

    inbound: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        inbound[e.target].append(e.source)

    memo: dict[str, int] = {}

    def layer(nid: str) -> int:
        if nid in memo:
            return memo[nid]
        if nid == root:
            memo[nid] = 0
            return 0
        preds = inbound.get(nid) or []
        if not preds:
            memo[nid] = 0
            return 0
        d = 1 + max(layer(p) for p in preds)
        memo[nid] = d
        return d

    depth_buckets: dict[int, list[str]] = defaultdict(list)
    for nid in graph.nodes:
        depth_buckets[layer(nid)].append(nid)

    for depth in sorted(depth_buckets):
        ids = sorted(depth_buckets[depth])
        for i, nid in enumerate(ids):
            node = graph.nodes[nid]
            node.canvas_x = depth * x_gap
            node.canvas_y = (i - (len(ids) - 1) / 2) * y_gap
