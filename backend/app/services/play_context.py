from __future__ import annotations

from typing import Any

from backend.app.models.story_graph import StoryGraph


def protagonist_from_blueprint(blueprint: dict[str, Any]) -> dict[str, str] | None:
    pid = blueprint.get("protagonist_character_id")
    if not pid:
        return None
    for c in blueprint.get("characters") or []:
        if c.get("character_id") == pid:
            return {"id": pid, "name": c.get("name") or "主角"}
    return {"id": pid, "name": "主角"}


def incoming_choice(graph: StoryGraph, node_id: str) -> tuple[str, str, str]:
    """返回 (选项文案, 来源节点标题, 来源节点摘要)。"""
    for opt in graph.options:
        if opt.to_node_id != node_id:
            continue
        from_node = graph.nodes.get(opt.from_node_id)
        from_title = from_node.title if from_node else ""
        from_summary = from_node.summary if from_node else ""
        return opt.label, from_title, from_summary
    return "", "", ""


def build_node_play_context(
    *,
    graph: StoryGraph,
    blueprint: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    node = graph.nodes.get(node_id)
    choice_label, from_title, from_summary = incoming_choice(graph, node_id)
    protagonist = protagonist_from_blueprint(blueprint)
    return {
        "protagonist_name": protagonist["name"] if protagonist else "主角",
        "protagonist_id": protagonist["id"] if protagonist else None,
        "player_choice": choice_label,
        "from_node_title": from_title,
        "from_node_summary": from_summary,
        "node_title": node.title if node else "",
        "node_summary": node.summary if node else "",
    }
