from __future__ import annotations

from collections import defaultdict

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph


def assign_mainline_kinds(
    graph: StoryGraph, key_events: list[str] | None = None
) -> None:
    """
    标定节点 kind：root 保持 root，主脉络链为 main，岔路为 branch，结局为 ending。
    主脉络优先沿 spine_event 与 key_events 顺序选取分支子节点。
    """
    events = [str(e).strip() for e in (key_events or []) if str(e).strip()]
    children: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        children[e.source].append(e.target)
    for src in children:
        children[src] = sorted(set(children[src]))

    def event_rank(nid: str) -> int:
        ev = (graph.nodes[nid].spine_event or "").strip()
        if not ev:
            return 10_000
        for i, ke in enumerate(events):
            if ev == ke or ev in ke or ke in ev:
                return i
        return 5_000

    def pick_child(kids: list[str]) -> str:
        if len(kids) == 1:
            return kids[0]
        return min(
            kids,
            key=lambda nid: (
                event_rank(nid),
                1 if graph.nodes[nid].kind == NodeKind.ending else 0,
                nid,
            ),
        )

    graph.nodes[graph.root_id].kind = NodeKind.root
    for nid, node in graph.nodes.items():
        if nid == graph.root_id:
            continue
        if node.kind == NodeKind.ending:
            continue
        node.kind = NodeKind.branch

    cur = graph.root_id
    for _ in range(len(graph.nodes) + 2):
        kids = children.get(cur) or []
        if not kids:
            break
        nxt = pick_child(kids)
        nxt_node = graph.nodes[nxt]
        if nxt_node.kind == NodeKind.ending:
            break
        nxt_node.kind = NodeKind.main
        cur = nxt


def spine_path_from_root(graph: StoryGraph) -> list[str]:
    """从 root 沿单链向下；若已有分支，优先走 main/ending 子节点。"""
    path: list[str] = []
    cur: str | None = graph.root_id
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        path.append(cur)
        children = [e.target for e in graph.edges if e.source == cur]
        if not children:
            break
        if len(children) == 1:
            cur = children[0]
            continue
        ranked = sorted(
            children,
            key=lambda nid: (
                0 if graph.nodes[nid].kind == NodeKind.main else 1
                if graph.nodes[nid].kind == NodeKind.ending
                else 2,
                nid,
            ),
        )
        cur = ranked[0]
    return path


def mainline_spine_complete(graph: StoryGraph) -> bool:
    """主线单链已写到 ending（尚无分支或仅 spine 上节点）。"""
    path = spine_path_from_root(graph)
    if len(path) < 2:
        return False
    leaf = path[-1]
    node = graph.nodes.get(leaf)
    if node is None or node.kind != NodeKind.ending:
        return False
    # spine 上除 ending 外不应出现 branch
    for nid in path[:-1]:
        if graph.nodes[nid].kind == NodeKind.branch:
            return False
    return True


def spine_plot_beat_count(graph: StoryGraph) -> int:
    """主链上剧情节拍数（main + ending，不含 root）。"""
    return sum(
        1
        for nid in spine_path_from_root(graph)
        if graph.nodes[nid].kind in (NodeKind.main, NodeKind.ending)
    )


def spine_tail_id(graph: StoryGraph) -> str | None:
    path = spine_path_from_root(graph)
    return path[-1] if path else None


def outbound_child_count(graph: StoryGraph) -> dict[str, int]:
    counts: dict[str, int] = {nid: 0 for nid in graph.nodes}
    for e in graph.edges:
        counts[e.source] = counts.get(e.source, 0) + 1
    return counts


def expandable_node_ids(graph: StoryGraph) -> list[str]:
    """非 ending 节点，稳定排序；下标即 expand_branch 的 at_node_index。"""
    return sorted(
        nid for nid, n in graph.nodes.items() if n.kind != NodeKind.ending
    )


def open_plot_leaf_ids(graph: StoryGraph) -> list[str]:
    """未收束开放叶，稳定排序；下标即 converge_endings 的 leaf_index。"""
    return sorted(graph.open_plot_leaves())


def mainline_node_ids(graph: StoryGraph) -> list[str]:
    """root 起 spine 顺序上的 root/main/ending 节点。"""
    path = spine_path_from_root(graph)
    if path:
        return [
            nid
            for nid in path
            if graph.nodes[nid].kind
            in (NodeKind.root, NodeKind.main, NodeKind.ending)
        ]
    return sorted(
        nid
        for nid, n in graph.nodes.items()
        if n.kind in (NodeKind.root, NodeKind.main)
    )


def spine_decision_candidates(graph: StoryGraph) -> list[str]:
    """主链上仍缺支线的 main/root：出边 < 2（只有主线后继，没有玩家岔路）。"""
    return unbranched_spine_main_ids(graph)


def later_spine_ids(graph: StoryGraph, from_id: str) -> list[str]:
    """from_id 之后的主链节点（含 ending），支线可汇回到这些共享剧情。"""
    path = spine_path_from_root(graph)
    if from_id in path:
        return path[path.index(from_id) + 1 :]
    from backend.app.services.plot_paths import can_reach

    return [
        nid
        for nid in path
        if nid != from_id and not can_reach(graph, nid, from_id)
    ]


def major_fork_ids(graph: StoryGraph, budget: int) -> list[str]:
    """均匀挑出允许「钻石汇回」的主线节点，其余 main 只用同目的地选项或 BE。"""
    mains = [
        nid
        for nid in spine_path_from_root(graph)
        if graph.nodes[nid].kind in (NodeKind.root, NodeKind.main)
    ]
    if not mains or budget <= 0:
        return []
    if len(mains) <= budget:
        return list(mains)
    picked: list[str] = []
    for i in range(budget):
        idx = round(i * (len(mains) - 1) / (budget - 1))
        nid = mains[idx]
        if nid not in picked:
            picked.append(nid)
    return picked


def multiplying_fork_count(graph: StoryGraph) -> int:
    """已形成的钻石岔口数：主线节点下有独立支线且该支线又连回主链。"""
    spine = spine_path_from_root(graph)
    spine_set = set(spine)
    used = 0
    for nid in spine:
        node = graph.nodes.get(nid)
        if node is None or node.kind not in (NodeKind.root, NodeKind.main):
            continue
        for edge in graph.edges:
            if edge.source != nid:
                continue
            child = edge.target
            if child in spine_set:
                continue
            if any(
                e.source == child and e.target in spine_set for e in graph.edges
            ):
                used += 1
                break
    return used


def unbranched_spine_main_ids(graph: StoryGraph) -> list[str]:
    """
    盛世天下式硬约束：每个 main/root 除主线后继外，必须再挂 ≥1 条支线。
    出边 < 2 即尚未裂变。
    """
    if not mainline_spine_complete(graph):
        return []
    path = spine_path_from_root(graph)
    counts = outbound_child_count(graph)
    out: list[str] = []
    for nid in path:
        n = graph.nodes[nid]
        if n.kind not in (NodeKind.root, NodeKind.main):
            continue
        if counts.get(nid, 0) < 2:
            out.append(nid)
    return out


def next_spine_successor(graph: StoryGraph, from_id: str) -> str | None:
    """主链上 from_id 的下一节点（用于表层分支 join）。"""
    path = spine_path_from_root(graph)
    if from_id not in path:
        return None
    idx = path.index(from_id)
    if idx + 1 >= len(path):
        return None
    return path[idx + 1]
