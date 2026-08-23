from __future__ import annotations

from collections import defaultdict, deque
from math import ceil, log2

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph

# 枚举上限：超过则只返回截断结果，计数必须走 DP
_ENUMERATE_CAP = 128


def multiplying_fork_budget(min_story_lines: int) -> int:
    """钻石分叉点数上限：2^k ≈ 目标线数。30 线 → 5 个乘性岔口。"""
    return max(3, min(6, ceil(log2(max(2, min_story_lines)))))


def plot_path_cap(min_story_lines: int) -> int:
    """历史启发式上限（min_paths+8）；仅作参考，Pass4 不再据此失败。"""
    return min_story_lines + 8


def _children_map(graph: StoryGraph) -> dict[str, list[str]]:
    """仅沿有向边 source→target 建子节点表（不是无向图）。"""
    children: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        children[edge.source].append(edge.target)
    for nid in children:
        children[nid] = sorted(set(children[nid]))
    return children


def ending_node_ids(graph: StoryGraph) -> set[str]:
    """结局节点 = 剧情线的合法终点。"""
    return {
        nid for nid, n in graph.nodes.items() if n.kind == NodeKind.ending
    }


def plot_path_terminals(graph: StoryGraph) -> set[str]:
    """路径终点：开放叶 + ending（用于裂变中途、开放分支计数）。"""
    terminals: set[str] = set(graph.open_plot_leaves())
    for nid in graph.leaf_ids():
        node = graph.nodes.get(nid)
        if node is not None and node.kind == NodeKind.ending:
            terminals.add(nid)
    return terminals


def root_to_ending_path_count(graph: StoryGraph) -> int:
    """
    剧情线数：root→ending 的不同有向路径条数（仅结局为终点）。
    用 DP 计数，不枚举。
    """
    endings = ending_node_ids(graph)
    if not endings or graph.root_id not in graph.nodes:
        return 0
    children = _children_map(graph)
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def ways(nid: str) -> int:
        if nid in memo:
            return memo[nid]
        if nid in visiting:
            return 0
        if nid in endings:
            memo[nid] = 1
            return 1
        visiting.add(nid)
        total = sum(ways(c) for c in children.get(nid, []))
        visiting.remove(nid)
        memo[nid] = total
        return total

    return ways(graph.root_id)


def enumerate_all_root_to_ending_paths(graph: StoryGraph) -> list[list[str]]:
    """
    枚举全部剧情线：每条为 root→ending 的一条有向简单路径。
    剧情线定义：起点 root、终点 ending、中间只沿 edges 正向走。
    """
    endings = ending_node_ids(graph)
    if not endings or graph.root_id not in graph.nodes:
        return []
    children = _children_map(graph)
    paths: list[list[str]] = []

    def dfs(nid: str, path: list[str]) -> None:
        if nid in endings:
            paths.append(list(path))
            return
        for child in children.get(nid, []):
            if child in path:
                continue
            dfs(child, path + [child])

    dfs(graph.root_id, [graph.root_id])
    return paths


def open_plot_path_count(graph: StoryGraph) -> int:
    """DAG 动态规划计路径数，避免 2^n 枚举卡死。"""
    if graph.root_id not in graph.nodes:
        return 0
    terminals = plot_path_terminals(graph)
    if not terminals:
        return graph.ending_inbound_count()
    children = _children_map(graph)
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def ways(nid: str) -> int:
        if nid in memo:
            return memo[nid]
        if nid in visiting:
            return 0
        if nid in terminals:
            memo[nid] = 1
            return 1
        visiting.add(nid)
        total = 0
        for child in children.get(nid, []):
            total += ways(child)
        visiting.remove(nid)
        memo[nid] = total
        return total

    return ways(graph.root_id)


def enumerate_paths_to_nodes(
    graph: StoryGraph,
    targets: set[str],
    *,
    cap: int = _ENUMERATE_CAP,
) -> list[list[str]]:
    """枚举 root→target 的简单路径，超过 cap 截断（计数请用 open_plot_path_count）。"""
    if graph.root_id not in graph.nodes or not targets:
        return []
    children = _children_map(graph)
    paths: list[list[str]] = []

    def dfs(nid: str, path: list[str]) -> None:
        if len(paths) >= cap:
            return
        if nid in targets:
            paths.append(list(path))
            return
        for child in children.get(nid, []):
            if child in path:
                continue
            dfs(child, path + [child])
            if len(paths) >= cap:
                return

    dfs(graph.root_id, [graph.root_id])
    return paths


def enumerate_plot_paths(graph: StoryGraph) -> list[list[str]]:
    """枚举剧情线（root→ending），超过 cap 时截断。"""
    return enumerate_paths_to_nodes(graph, ending_node_ids(graph))


def enumerate_open_plot_paths(graph: StoryGraph) -> list[list[str]]:
    """裂变中途：root 到开放叶或 ending 的路径（非收束剧情线）。"""
    return enumerate_paths_to_nodes(graph, plot_path_terminals(graph))


def min_path_depth_to(graph: StoryGraph, node_id: str) -> int:
    """最短 root→node 节点数（BFS，不枚举全部路径）。"""
    if graph.root_id not in graph.nodes:
        return 0
    children = _children_map(graph)
    q: deque[tuple[str, int]] = deque([(graph.root_id, 1)])
    seen = {graph.root_id}
    while q:
        nid, depth = q.popleft()
        if nid == node_id:
            return depth
        for child in children.get(nid, []):
            if child in seen:
                continue
            seen.add(child)
            q.append((child, depth + 1))
    return 0


def max_path_depth_to(graph: StoryGraph, node_id: str) -> int:
    if graph.root_id not in graph.nodes:
        return 0
    children = _children_map(graph)
    best = 0
    stack = [(graph.root_id, 1, {graph.root_id})]
    while stack:
        nid, depth, seen = stack.pop()
        if nid == node_id:
            if depth > best:
                best = depth
            continue
        for child in children.get(nid, []):
            if child in seen:
                continue
            stack.append((child, depth + 1, seen | {child}))
    return best


def min_terminal_path_depth(graph: StoryGraph) -> int:
    terminals = plot_path_terminals(graph)
    if not terminals:
        return 0
    depths = [min_path_depth_to(graph, t) for t in terminals]
    return min(depths) if depths else 0


def can_reach(graph: StoryGraph, src: str, dst: str) -> bool:
    if src == dst:
        return True
    children = _children_map(graph)
    stack = [src]
    seen: set[str] = set()
    while stack:
        nid = stack.pop()
        if nid == dst:
            return True
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(children.get(nid, []))
    return False


def joinable_node_indices(
    graph: StoryGraph,
    from_node_id: str,
    expandable: list[str],
) -> list[int]:
    """可汇合下标。同目的地、不同选项允许（不加倍路径）。"""
    out: list[int] = []
    for i, nid in enumerate(expandable):
        if nid == from_node_id:
            continue
        if can_reach(graph, nid, from_node_id):
            continue
        out.append(i)
    return out
