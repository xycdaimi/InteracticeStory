from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from backend.app.models.fission_config import FissionConfig
from backend.app.models.plot_tree import PlotTreeEdge, PlotTreeOutline, PlotTreeNode


@dataclass(frozen=True)
class PlotTreeGraph:
    """剧情树图：选择边与汇合边分离，避免把 rejoin 误判为分叉。"""

    root_id: str
    by_id: dict[str, PlotTreeNode]
    choice_children: dict[str, list[str]]
    rejoin_children: dict[str, list[str]]
    inbound_choice: dict[str, list[str]]


def normalize_plot_tree_outline(outline: PlotTreeOutline) -> PlotTreeOutline:
    """合并 parent 与 edges（模型常漏写 edges 条目）。"""
    if not outline.edges:
        return outline

    by_id = {n.id: n for n in outline.nodes}
    edges = list(outline.edges)
    pairs = {(e.from_id, e.to_id) for e in edges}

    for n in outline.nodes:
        if n.id == outline.root or not n.parent:
            continue
        if n.parent not in by_id:
            continue
        key = (n.parent, n.id)
        if key not in pairs:
            label = (n.option_label or "").strip() or "继续"
            edges.append(PlotTreeEdge(**{"from": n.parent, "to": n.id, "label": label}))
            pairs.add(key)

    inbound: dict[str, str] = {}
    for e in edges:
        if e.to_id not in inbound:
            inbound[e.to_id] = e.from_id

    for n in outline.nodes:
        if n.id == outline.root:
            continue
        if not n.parent and n.id in inbound:
            n.parent = inbound[n.id]

    return PlotTreeOutline(root=outline.root, nodes=outline.nodes, edges=edges)


def build_plot_tree_graph(outline: PlotTreeOutline) -> tuple[PlotTreeGraph, list[str]]:
    """构建图结构；返回 (graph, 结构错误)。"""
    errors: list[str] = []
    by_id = {n.id: n for n in outline.nodes}
    root_id = outline.root

    choice_children: dict[str, list[str]] = defaultdict(list)
    rejoin_children: dict[str, list[str]] = defaultdict(list)
    inbound_choice: dict[str, list[str]] = defaultdict(list)
    choice_pairs: set[tuple[str, str]] = set()

    if outline.edges:
        for e in outline.edges:
            if e.from_id not in by_id:
                errors.append(f"边 from={e.from_id!r} 不在 nodes 中")
                continue
            if e.to_id not in by_id:
                errors.append(f"边 to={e.to_id!r} 不在 nodes 中")
                continue
            choice_pairs.add((e.from_id, e.to_id))
            choice_children[e.from_id].append(e.to_id)
            inbound_choice[e.to_id].append(e.from_id)
        for n in outline.nodes:
            if n.id == root_id or not n.parent:
                continue
            if n.parent not in by_id:
                continue
            key = (n.parent, n.id)
            if key not in choice_pairs:
                choice_pairs.add(key)
                choice_children[n.parent].append(n.id)
                inbound_choice[n.id].append(n.parent)
    else:
        for n in outline.nodes:
            if not n.parent:
                continue
            if n.parent not in by_id:
                errors.append(f"节点 {n.id} 的 parent={n.parent!r} 不存在")
                continue
            choice_pairs.add((n.parent, n.id))
            choice_children[n.parent].append(n.id)
            inbound_choice[n.id].append(n.parent)

    for n in outline.nodes:
        if not n.rejoin:
            continue
        if n.rejoin not in by_id:
            errors.append(f"节点 {n.id} 的 rejoin={n.rejoin!r} 不存在")
        else:
            rejoin_children[n.id].append(n.rejoin)

    if outline.edges:
        for n in outline.nodes:
            if n.id == root_id:
                continue
            if not inbound_choice.get(n.id):
                errors.append(f"节点 {n.id} 无入边（parent/edges 均未连接上游）")

    graph = PlotTreeGraph(
        root_id=root_id,
        by_id=by_id,
        choice_children=dict(choice_children),
        rejoin_children=dict(rejoin_children),
        inbound_choice=dict(inbound_choice),
    )
    return graph, errors


def _all_children(graph: PlotTreeGraph, nid: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tgt in graph.choice_children.get(nid, []):
        if tgt not in seen:
            seen.add(tgt)
            out.append(tgt)
    for tgt in graph.rejoin_children.get(nid, []):
        if tgt not in seen:
            seen.add(tgt)
            out.append(tgt)
    return out


def plot_tree_has_cycle(graph: PlotTreeGraph) -> bool:
    """检测从 root 出发是否存在环（rejoin 指向上游时常见）。"""
    if graph.root_id not in graph.by_id:
        return False
    # 0=未访问 1=栈中 2=已完成
    state: dict[str, int] = {nid: 0 for nid in graph.by_id}
    stack: list[tuple[str, int]] = [(graph.root_id, 0)]

    while stack:
        nid, ci = stack[-1]
        if state.get(nid, 0) == 2:
            stack.pop()
            continue
        children = _all_children(graph, nid)
        if state.get(nid, 0) == 0:
            state[nid] = 1
        if ci < len(children):
            stack[-1] = (nid, ci + 1)
            child = children[ci]
            st = state.get(child, 0)
            if st == 1:
                return True
            if st == 0:
                stack.append((child, 0))
        else:
            state[nid] = 2
            stack.pop()
    return False


def fork_nodes(graph: PlotTreeGraph) -> set[str]:
    """有 ≥2 条「选择出边」的节点（不含 rejoin）。"""
    forks: set[str] = set()
    for src, tgts in graph.choice_children.items():
        uniq = list(dict.fromkeys(tgts))
        if len(uniq) >= 2:
            forks.add(src)
    return forks


def max_choice_fanout(graph: PlotTreeGraph) -> int:
    """任意节点上最多的选择出边数（不含 rejoin）。"""
    best = 0
    for tgts in graph.choice_children.values():
        best = max(best, len(dict.fromkeys(tgts)))
    return best


def estimate_plot_path_count(graph: PlotTreeGraph) -> int:
    """从剧情树结构估算 root→ending 路径数（含 rejoin）；迭代 DP，避免环/深链递归爆栈。"""
    ending_ids = {nid for nid, n in graph.by_id.items() if n.type == "ending"}
    if not ending_ids or graph.root_id not in graph.by_id:
        return 0
    if plot_tree_has_cycle(graph):
        return 0

    memo: dict[str, int] = {eid: 1 for eid in ending_ids}
    pending = True
    guard = 0
    while pending and guard < len(graph.by_id) + 2:
        guard += 1
        pending = False
        for nid in graph.by_id:
            if nid in memo:
                continue
            kids = _all_children(graph, nid)
            if not kids:
                memo[nid] = 0
                pending = True
                continue
            if all(c in memo for c in kids):
                memo[nid] = sum(memo[c] for c in kids)
                pending = True
    return memo.get(graph.root_id, 0)


def validate_plot_tree(outline: PlotTreeOutline, config: FissionConfig) -> list[str]:
    """硬校验剧情树结构；返回错误列表（空=通过）。"""
    graph, errors = build_plot_tree_graph(outline)
    if errors:
        return errors

    root_id = graph.root_id
    root = graph.by_id.get(root_id)
    if root is None:
        return ["root 不在 nodes 中"]

    if root.parent is not None:
        errors.append(f"start/root {root_id} 不得有 parent")
    if graph.inbound_choice.get(root_id):
        errors.append(f"start/root {root_id} 不得有入边")
    if root.type != "start":
        errors.append(f"root 节点 type 应为 start，实际为 {root.type}")

    starts = [n for n in outline.nodes if n.type == "start"]
    if len(starts) != 1 or starts[0].id != root_id:
        errors.append("必须恰好一个 type=start 且等于 root")

    endings = [n for n in outline.nodes if n.type == "ending"]
    for n in endings:
        outs = _all_children(graph, n.id)
        if outs:
            errors.append(f"ending {n.id} 不得有出边: {outs}")
        if not n.outcome:
            errors.append(f"ending {n.id} 缺少 outcome")

    reachable: set[str] = set()
    q: deque[str] = deque([root_id])
    while q:
        cur = q.popleft()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in _all_children(graph, cur):
            if nxt not in reachable:
                q.append(nxt)
    orphans = [n.id for n in outline.nodes if n.id not in reachable]
    if orphans:
        errors.append(f"孤立节点（从 root 不可达）: {orphans}")

    ending_ids = {n.id for n in endings}
    can_reach_ending: set[str] = set(ending_ids)
    rev: dict[str, list[str]] = defaultdict(list)
    for nid in graph.by_id:
        for nxt in _all_children(graph, nid):
            rev[nxt].append(nid)
    rq: deque[str] = deque(ending_ids)
    while rq:
        cur = rq.popleft()
        for prev in rev.get(cur) or []:
            if prev not in can_reach_ending:
                can_reach_ending.add(prev)
                rq.append(prev)
    for n in outline.nodes:
        if n.type == "ending":
            continue
        if n.id not in can_reach_ending:
            errors.append(f"节点 {n.id} 无法到达任何 ending")

    # branch_depth = 单节点最大子分支数（选择出边数上限，非剧情链层数）
    max_fan = int(config.branch_depth)
    min_choices = 2
    for nid, node in graph.by_id.items():
        if node.type == "ending":
            continue
        uniq = list(dict.fromkeys(graph.choice_children.get(nid) or []))
        if len(uniq) > max_fan:
            errors.append(
                f"节点 {nid} 子分支数 {len(uniq)} > branch_depth={max_fan}"
                "（branch_depth=单节点最大子分支数，不是剧情深度）"
            )
        if len(uniq) < min_choices:
            errors.append(
                f"节点 {nid}（{node.title}）仅有 {len(uniq)} 个选项，"
                f"互动节点至少需要 {min_choices} 个（ending 无子节点除外）"
            )

    has_cycle = plot_tree_has_cycle(graph)
    path_count = estimate_plot_path_count(graph)
    if has_cycle:
        errors.append(
            "剧情树存在环（常见于 rejoin 指向上游或汇合形成回路）；"
            "rejoin 只能指向尚未走过的下游汇合点"
        )
    elif path_count < int(config.min_paths):
        errors.append(
            f"剧情线路径数 {path_count} < min_paths={config.min_paths}"
            f"（从 root 到各 ending 的不同完整路径；每个分叉点 ≤{max_fan} 条出路，"
            "可增加分叉层级或结局节点来凑路径数）"
        )

    min_endings = max(2, int(config.ending_targets.completed))
    if len(endings) < min_endings:
        errors.append(
            f"结局数 {len(endings)} < 下限 {min_endings}"
            f"（至少 {min_endings} 个 ending 节点）"
        )

    return errors
