from __future__ import annotations

from backend.app.models.story_graph import StoryGraph
from backend.app.services.graph_refs import spine_path_from_root, unbranched_spine_main_ids
from backend.app.services.plot_paths import (
    min_path_depth_to,
    open_plot_path_count,
)
from backend.app.services.story_spine_store import load_story_spine


def path_from_root(graph: StoryGraph, node_id: str) -> list[str]:
    chain: list[str] = []
    cur: str | None = node_id
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        node = graph.nodes.get(cur)
        if node is None or not node.parent_id:
            break
        cur = node.parent_id
    chain.reverse()
    return chain


def mainline_path_node_count(graph: StoryGraph) -> int:
    return len(spine_path_from_root(graph))


def min_required_path_depth(graph: StoryGraph) -> int:
    """支线收束前，每条开放路径至少应达到的节点数（接近主线篇幅）。"""
    ml = mainline_path_node_count(graph)
    return max(8, ml - 1)


def shallow_open_leaves(
    graph: StoryGraph,
    min_depth: int | None = None,
) -> list[dict[str, object]]:
    """过浅路径：按最短 root→叶 路径计深度（汇合后多路径共享叶时取最短）。"""
    min_depth = min_depth if min_depth is not None else min_required_path_depth(graph)
    out: list[dict[str, object]] = []
    for i, leaf_id in enumerate(sorted(graph.open_plot_leaves())):
        depth = min_path_depth_to(graph, leaf_id)
        if depth < min_depth:
            node = graph.nodes[leaf_id]
            out.append(
                {
                    "leaf_index": i,
                    "node_id": leaf_id,
                    "title": node.title,
                    "depth": depth,
                    "required_depth": min_depth,
                }
            )
    return out


def depth_ready_open_leaves(graph: StoryGraph, min_depth: int | None = None) -> list[str]:
    min_depth = min_depth if min_depth is not None else min_required_path_depth(graph)
    return [
        lid
        for lid in sorted(graph.open_plot_leaves())
        if min_path_depth_to(graph, lid) >= min_depth
    ]


def depth_ready_path_count(graph: StoryGraph, min_depth: int | None = None) -> int:
    """
    深度达标的开放叶条数（有开放叶时）。
    无开放叶时返回总路径数（若最短终端达标）。
    """
    min_depth = min_depth if min_depth is not None else min_required_path_depth(graph)
    open_leaves = graph.open_plot_leaves()
    if open_leaves:
        return sum(1 for lid in open_leaves if min_path_depth_to(graph, lid) >= min_depth)
    from backend.app.services.plot_paths import min_terminal_path_depth

    if min_terminal_path_depth(graph) >= min_depth:
        return open_plot_path_count(graph)
    return 0


def can_converge_plot_lines(graph: StoryGraph, min_lines: int) -> bool:
    if unbranched_spine_main_ids(graph):
        return False
    if open_plot_path_count(graph) < min_lines:
        return False
    if shallow_open_leaves(graph):
        return False
    open_leaves = graph.open_plot_leaves()
    if open_leaves:
        min_depth = min_required_path_depth(graph)
        return all(min_path_depth_to(graph, lid) >= min_depth for lid in open_leaves)
    from backend.app.services.plot_paths import min_terminal_path_depth

    return min_terminal_path_depth(graph) >= min_required_path_depth(graph)


def completion_point_hint(story_id: str) -> str:
    spine = load_story_spine(story_id)
    return spine.completion_point if spine else ""
