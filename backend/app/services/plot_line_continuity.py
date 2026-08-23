from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.story_graph import PlotLine, StoryGraph
from backend.app.services.script_continuity import (
    ContinuityIssue,
    _beat_text,
    check_node_script,
)


def option_label_between(graph: StoryGraph, from_id: str, to_id: str) -> str:
    for opt in graph.options:
        if opt.from_node_id == from_id and opt.to_node_id == to_id:
            return (opt.label or "").strip()
    return ""


def check_plot_line_continuity(
    graph: StoryGraph,
    line: PlotLine,
) -> list[ContinuityIssue]:
    """沿单条剧情线逐步校验：只检查该线上的父→子转移，不按 DAG 全量父节点扫。"""
    issues: list[ContinuityIssue] = []
    path = line.node_path
    if len(path) < 2:
        return issues

    for i in range(1, len(path)):
        parent_id = path[i - 1]
        child_id = path[i]
        child = graph.nodes.get(child_id)
        parent = graph.nodes.get(parent_id)
        if child is None or parent is None:
            continue

        issues.extend(check_node_script(child_id, child.script))
        if child.script is None:
            continue

        label = option_label_between(graph, parent_id, child_id)
        if parent_id == graph.root_id and parent.script is None:
            if label and label not in _beat_text(child.script):
                issues.append(
                    ContinuityIssue(
                        code="CHOICE_NOT_GROUNDED",
                        node_id=child_id,
                        message=f"剧情线 {line.line_id} 开场未体现选项:{label}",
                        plot_line_id=line.line_id,
                        parent_id=parent_id,
                        option_label=label,
                    )
                )
            continue

        if parent.script is None:
            issues.append(
                ContinuityIssue(
                    code="NO_SCRIPT",
                    node_id=parent_id,
                    message=f"剧情线 {line.line_id} 上游节点无 script",
                    plot_line_id=line.line_id,
                    parent_id=parent_id,
                )
            )
            continue

        pout = parent.script.dramatic_state_out.strip()
        cin = child.script.dramatic_state_in.strip()
        prefix = pout[: min(20, len(pout))] if pout else ""
        if pout and prefix and prefix not in cin and not cin.startswith(prefix):
            issues.append(
                ContinuityIssue(
                    code="STATE_BREAK",
                    node_id=child_id,
                    message=(
                        f"剧情线 {line.line_id} 未承接上游状态"
                        f"（{parent.title}→{child.title}）: {pout[:40]}"
                    ),
                    plot_line_id=line.line_id,
                    parent_id=parent_id,
                    option_label=label,
                )
            )
        if label and label not in _beat_text(child.script):
            issues.append(
                ContinuityIssue(
                    code="CHOICE_NOT_GROUNDED",
                    node_id=child_id,
                    message=f"剧情线 {line.line_id} 开场未体现选项:{label}",
                    plot_line_id=line.line_id,
                    parent_id=parent_id,
                    option_label=label,
                )
            )
    return issues


def check_all_plot_lines(graph: StoryGraph) -> list[ContinuityIssue]:
    """枚举全部剧情线并逐条校验连贯性。"""
    seen: set[tuple[str, str, str, str | None]] = set()
    out: list[ContinuityIssue] = []
    for line in graph.iter_plot_lines():
        for issue in check_plot_line_continuity(graph, line):
            key = (issue.code, issue.node_id, issue.message, issue.plot_line_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(issue)
    return out


def continuity_issue_to_dict(issue: ContinuityIssue) -> dict:
    return {
        "code": issue.code,
        "message": issue.message,
        "node_id": issue.node_id,
        "plot_line_id": issue.plot_line_id,
        "parent_id": issue.parent_id,
        "option_label": issue.option_label,
    }
