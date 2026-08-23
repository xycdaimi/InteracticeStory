from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.story_graph import StoryGraph, validate_visual_plan


@dataclass
class ContinuityIssue:
    code: str
    node_id: str
    message: str
    plot_line_id: str | None = None
    parent_id: str | None = None
    option_label: str | None = None


def _beat_text(script) -> str:
    if not script or not script.beats:
        return ""
    beat = script.beats[0]
    parts = [beat.shot or "", beat.action or ""]
    for d in beat.dialogue:
        parts.append(d.speaker or "")
        parts.append(d.line or "")
    return "".join(parts)


def check_node_script(node_id: str, script) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    if script is None:
        return [ContinuityIssue("NO_SCRIPT", node_id, "节点无 script")]
    try:
        validate_visual_plan(script)
    except ValueError as exc:
        issues.append(ContinuityIssue("VISUAL_PLAN", node_id, str(exc)))
    if not any(b.dialogue for b in script.beats):
        issues.append(ContinuityIssue("NO_DIALOGUE", node_id, "无对白"))
    prev_end = None
    for b in script.beats:
        if b.t_end <= b.t_start:
            issues.append(ContinuityIssue("BEAT_TIMING", node_id, "时码无效"))
        if prev_end is not None and b.t_start + 1e-6 < prev_end:
            issues.append(ContinuityIssue("BEAT_TIMING", node_id, "时码重叠"))
        prev_end = b.t_end
    return issues


def check_parent_children(graph: StoryGraph, parent_id: str) -> list[ContinuityIssue]:
    parent = graph.nodes.get(parent_id)
    issues: list[ContinuityIssue] = []
    if parent is None:
        return [ContinuityIssue("NO_SCRIPT", parent_id, "父节点不存在")]
    if not parent.script:
        # 根节点可无 script；其余父节点应有
        if parent_id != graph.root_id:
            issues.append(ContinuityIssue("NO_SCRIPT", parent_id, "父节点无 script"))
        return issues

    pout = parent.script.dramatic_state_out.strip()
    for opt in graph.options:
        if opt.from_node_id != parent_id:
            continue
        child = graph.nodes.get(opt.to_node_id)
        if child is None:
            continue
        issues.extend(check_node_script(child.id, child.script))
        if not child.script:
            continue
        cin = child.script.dramatic_state_in.strip()
        prefix = pout[: min(20, len(pout))] if pout else ""
        if pout and prefix and prefix not in cin and not cin.startswith(prefix):
            issues.append(
                ContinuityIssue(
                    "STATE_BREAK",
                    child.id,
                    f"未承接父状态: {pout[:40]}",
                )
            )
        label = (opt.label or "").strip()
        if label and label not in _beat_text(child.script):
            issues.append(
                ContinuityIssue(
                    "CHOICE_NOT_GROUNDED",
                    child.id,
                    f"开场未体现选项:{label}",
                )
            )
    return issues


def check_graph_scripts(graph: StoryGraph) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    for nid, node in graph.nodes.items():
        if nid == graph.root_id:
            continue
        issues.extend(check_node_script(nid, node.script))
    parents = {opt.from_node_id for opt in graph.options}
    for pid in parents:
        issues.extend(check_parent_children(graph, pid))
    # dedupe
    seen: set[tuple[str, str, str]] = set()
    uniq: list[ContinuityIssue] = []
    for issue in issues:
        key = (issue.code, issue.node_id, issue.message)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(issue)
    return uniq
