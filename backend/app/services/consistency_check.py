from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from backend.app.models.enums import NodeKind
from backend.app.services.plot_paths import root_to_ending_path_count
from backend.app.services.script_continuity import check_node_script
from backend.app.services.story_repository import StoryRepository


def check_consistency(story_id: str) -> list[dict[str, Any]]:
    """结构校验 + 节点剧本硬指标（不做 DAG AI 删改）。"""
    repo = StoryRepository()
    graph = repo.load_graph(story_id)
    config = repo.ensure_fission_config(story_id)
    issues: list[dict[str, Any]] = []

    children: dict[str, list[str]] = defaultdict(list)
    for opt in graph.options:
        children[opt.from_node_id].append(opt.to_node_id)

    for nid, node in graph.nodes.items():
        if nid == graph.root_id:
            continue
        if node.script is None:
            issues.append(
                {
                    "code": "missing_script",
                    "message": "非 root 节点缺少 script",
                    "node_id": nid,
                }
            )
        else:
            for issue in check_node_script(nid, node.script):
                if issue.code in {"NO_DIALOGUE", "VISUAL_PLAN", "BEAT_TIMING"}:
                    issues.append(
                        {
                            "code": issue.code,
                            "message": issue.message,
                            "node_id": nid,
                        }
                    )

    for nid, node in graph.nodes.items():
        if nid == graph.root_id:
            continue
        if node.kind == NodeKind.ending:
            continue
        uniq_kids = list(dict.fromkeys(children.get(nid) or []))
        if len(uniq_kids) < 2:
            issues.append(
                {
                    "code": "choice_count_low",
                    "message": (
                        f"非 ending 节点仅有 {len(uniq_kids)} 个选项"
                        "（互动节点至少 2 个）"
                    ),
                    "node_id": nid,
                }
            )
        if len(uniq_kids) > int(config.branch_depth):
            issues.append(
                {
                    "code": "choice_count_high",
                    "message": (
                        f"选项数 {len(uniq_kids)} > branch_depth="
                        f"{config.branch_depth}"
                    ),
                    "node_id": nid,
                }
            )

    for nid, node in graph.nodes.items():
        if nid == graph.root_id:
            continue
        if node.kind == NodeKind.ending:
            continue
        if not children.get(nid):
            issues.append(
                {
                    "code": "dead_end",
                    "message": "非 ending 节点无出边",
                    "node_id": nid,
                }
            )

    ending_ids = {
        nid for nid, n in graph.nodes.items() if n.kind == NodeKind.ending
    }
    can_reach_ending: set[str] = set(ending_ids)
    rev: dict[str, list[str]] = defaultdict(list)
    for src, tgts in children.items():
        for t in tgts:
            rev[t].append(src)
    rq: deque[str] = deque(ending_ids)
    while rq:
        cur = rq.popleft()
        for prev in rev.get(cur) or []:
            if prev not in can_reach_ending:
                can_reach_ending.add(prev)
                rq.append(prev)
    for nid in graph.nodes:
        if nid not in can_reach_ending:
            issues.append(
                {
                    "code": "unreachable_ending",
                    "message": "无法到达任何 ending",
                    "node_id": nid,
                }
            )

    ending_titles = [
        (nid, (n.title or "").strip())
        for nid, n in graph.nodes.items()
        if n.kind == NodeKind.ending
    ]
    if len(ending_titles) >= 2:
        titles = [t for _, t in ending_titles if t]
        if len(titles) != len(set(titles)):
            issues.append(
                {
                    "code": "ending_title_dup",
                    "message": "存在 2+ ending 但标题不完全互异",
                    "node_id": ending_titles[0][0],
                }
            )

    min_paths = int(config.min_paths)
    path_count = root_to_ending_path_count(graph)
    if path_count < min_paths:
        issues.append(
            {
                "code": "path_count_low",
                "message": f"剧情线数 {path_count} < min_paths={min_paths}",
                "node_id": graph.root_id,
            }
        )

    seen: set[tuple[str, str, str]] = set()
    uniq: list[dict[str, Any]] = []
    for item in issues:
        key = (item["code"], item["node_id"], item["message"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq

