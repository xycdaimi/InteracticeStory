from __future__ import annotations

from backend.app.infrastructure.paths import spine_path
from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph
from backend.app.models.story_spine import StorySpine
from backend.app.services.graph_refs import spine_path_from_root


def load_story_spine(story_id: str) -> StorySpine | None:
    path = spine_path(story_id)
    if not path.exists():
        return None
    return StorySpine.model_validate_json(path.read_text(encoding="utf-8"))


def save_story_spine(story_id: str, spine: StorySpine) -> None:
    path = spine_path(story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(spine.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def event_is_covered(blob: str, event: str) -> bool:
    ev = event.strip()
    if not ev:
        return False
    if ev in blob:
        return True
    head = ev[: min(12, len(ev))]
    return bool(head and head in blob)


def match_spine_event_index(ref: str, key_events: list[str]) -> int | None:
    """节点 spine_event 对应骨架中的第几项（0-based）。"""
    ref = ref.strip()
    if not ref:
        return None
    for i, ev in enumerate(key_events):
        if ref == ev.strip():
            return i
    for i, ev in enumerate(key_events):
        if event_is_covered(ref, ev):
            return i
    return None


def mainline_spine_event_refs(graph: StoryGraph) -> list[str]:
    """主链上各可拍节点的 spine_event（按路径顺序）。"""
    refs: list[str] = []
    for nid in spine_path_from_root(graph):
        n = graph.nodes[nid]
        if n.kind not in (NodeKind.main, NodeKind.ending):
            continue
        if n.spine_event:
            refs.append(n.spine_event.strip())
    return refs


def spine_events_covered_indices(refs: list[str], key_events: list[str]) -> set[int]:
    seen: set[int] = set()
    for ref in refs:
        idx = match_spine_event_index(ref, key_events)
        if idx is not None:
            seen.add(idx)
    return seen


def validate_mainline_spine_coverage(
    refs: list[str],
    key_events: list[str],
    *,
    finalize: bool,
) -> list[str]:
    """
    校验主链节点与关键事件的关系：
    - 多个节点可同属一个关键事件；
    - 事件须按骨架顺序出现，不可倒退或跳项；
    - finalize 时须覆盖全部关键事件且末节点落在完成点事件上。
    """
    issues: list[str] = []
    if not refs:
        issues.append("主线节点为空")
        return issues
    if not key_events:
        issues.append("故事骨架无关键事件")
        return issues

    seen: set[int] = set()
    prev = -1
    for i, ref in enumerate(refs):
        idx = match_spine_event_index(ref, key_events)
        if idx is None:
            issues.append(f"第{i + 1}节点未对应关键事件：{ref[:40]}")
            continue
        if prev >= 0 and idx < prev:
            issues.append(
                f"第{i + 1}节点事件顺序倒退：{key_events[idx][:30]} "
                f"出现在 {key_events[prev][:30]} 之后"
            )
        elif idx > prev + 1:
            skipped = key_events[prev + 1 : idx]
            issues.append(
                "第"
                f"{i + 1}节点跳过关键事件："
                + "；".join(s[:25] for s in skipped)
            )
        seen.add(idx)
        prev = max(prev, idx)

    if finalize:
        missing = [key_events[j] for j in range(len(key_events)) if j not in seen]
        if missing:
            issues.append(
                f"未覆盖关键事件（{len(missing)} 项）："
                + "；".join(m[:25] for m in missing[:5])
            )
        if prev != len(key_events) - 1:
            issues.append("末节点须落在最后一项关键事件（完成点）上")
    return issues


def completion_point_reached(spine: StorySpine, final_state_out: str) -> bool:
    cp = spine.completion_point.strip()
    out = final_state_out.strip()
    if not cp or not out:
        return False
    if cp in out or out in cp:
        return True
    head = cp[: min(15, len(cp))]
    return bool(head and head in out)
