from __future__ import annotations

import json
from typing import Any

from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.ai.message_compat import dict_messages_to_lc, lc_response_to_openai
from backend.app.models.enums import FissionPhase
from backend.app.models.story_graph import NodeScript, StoryGraph
from backend.app.services.dag_outline import build_dag_compliance_prompt, export_dag_outline
from backend.app.services.layout import apply_layout
from backend.app.services.plot_line_continuity import option_label_between
from backend.app.services.plot_paths import root_to_ending_path_count
from backend.app.services.script_sanitize import ground_branch_script, sanitize_script_dict
from backend.app.services.story_repository import StoryRepository

_MAX_REMOVE_BRANCH_PER_ROUND = 1


def remove_branch_edge(graph: StoryGraph, from_id: str, to_id: str) -> bool:
    """仅删除一条选项边，不删节点、不清理其他剧情线。"""
    before = len(graph.options)
    graph.options = [
        o
        for o in graph.options
        if o.from_node_id != from_id or o.to_node_id != to_id
    ]
    graph.edges = [
        e
        for e in graph.edges
        if not (e.source == from_id and e.target == to_id)
    ]
    return len(graph.options) < before


def update_choice_label(
    graph: StoryGraph, from_id: str, to_id: str, label: str
) -> bool:
    label = label.strip()
    if not label:
        return False
    changed = False
    for opt in graph.options:
        if opt.from_node_id == from_id and opt.to_node_id == to_id:
            opt.label = label
            changed = True
    for edge in graph.edges:
        if edge.source == from_id and edge.target == to_id and edge.option_id:
            for opt in graph.options:
                if opt.id == edge.option_id:
                    opt.label = label
    return changed


async def _lc_chat_tool_args(
    *,
    messages: list[dict[str, Any]],
    tool_name: str,
    tool_schema: dict[str, Any],
) -> dict[str, Any]:
    fn_schema = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_schema.get("description", ""),
            "parameters": tool_schema.get("parameters", tool_schema),
        },
    }
    llm = get_geekai_chat_model().bind_tools(
        [fn_schema], tool_choice={"type": "function", "function": {"name": tool_name}}
    )
    resp = await llm.ainvoke(dict_messages_to_lc(messages))
    data = lc_response_to_openai(resp)
    message = (data.get("choices") or [{}])[0].get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        content = str(message.get("content") or "").strip()
        if content:
            return json.loads(content)
        raise ValueError(f"模型未调用工具 {tool_name}")
    fn = tool_calls[0].get("function") or {}
    raw = fn.get("arguments") or "{}"
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


async def apply_dag_compliance_once(story_id: str, inspiration: str) -> bool:
    """
    一轮 DAG 合规扫描：优先修改敏感内容；仅无法修改时才删一条分支边。
    不批量删节点、不清理不可达子图。
    """
    repo = StoryRepository()
    graph = repo.load_graph(story_id)
    config = repo.ensure_fission_config(story_id)
    min_paths = int(config.min_paths)
    outline = export_dag_outline(graph)

    from backend.app.agents.fission_tools import FissionTools, _SCRIPT_JSON_SCHEMA

    prompt = build_dag_compliance_prompt(outline=outline, inspiration=inspiration)
    tool_schema = {
        "description": "一轮 DAG 合规审查与修复（优先修改）",
        "parameters": {
            "type": "object",
            "properties": {
                "analysis": {"type": "string"},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type", "reason"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "update_node",
                                    "update_choice",
                                    "rewrite_script",
                                    "remove_branch",
                                ],
                            },
                            "node_id": {"type": "string"},
                            "from_node_id": {"type": "string"},
                            "to_node_id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "label": {"type": "string"},
                            "script": _SCRIPT_JSON_SCHEMA,
                            "cannot_fix_reason": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["analysis", "actions"],
        },
    }

    data = await _lc_chat_tool_args(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是内容合规编辑。只通过 submit_dag_compliance 提交结果。"
                    "默认修改，禁止批量删除剧情线。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        tool_name="submit_dag_compliance",
        tool_schema=tool_schema,
    )

    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        repo.append_event(
            story_id,
            phase=FissionPhase.compliance,
            type="log",
            message="DAG 合规扫描：未发现问题",
            payload={"analysis": str(data.get("analysis") or "")[:300]},
        )
        return False

    modified = False
    script_updates: list[dict[str, Any]] = []
    remove_count = 0

    for act in actions:
        if not isinstance(act, dict):
            continue
        kind = str(act.get("type") or "").strip()

        if kind == "update_node":
            nid = str(act.get("node_id") or "").strip()
            if not nid or nid not in graph.nodes:
                continue
            node = graph.nodes[nid]
            title = str(act.get("title") or "").strip()
            summary = str(act.get("summary") or "").strip()
            if title:
                node.title = title
                modified = True
            if summary:
                node.summary = summary[:80]
                modified = True
            continue

        if kind == "update_choice":
            fr = str(act.get("from_node_id") or "").strip()
            to = str(act.get("to_node_id") or "").strip()
            label = str(act.get("label") or "").strip()
            if fr and to and update_choice_label(graph, fr, to, label):
                modified = True
            continue

        if kind == "rewrite_script":
            nid = str(act.get("node_id") or "").strip()
            raw_script = act.get("script")
            if not nid or not isinstance(raw_script, dict) or nid not in graph.nodes:
                continue
            parent_id = graph.nodes[nid].parent_id
            parent_out = ""
            label = ""
            if parent_id and parent_id in graph.nodes:
                parent = graph.nodes[parent_id]
                if parent.script:
                    parent_out = parent.script.dramatic_state_out
                label = option_label_between(graph, parent_id, nid)
            grounded = ground_branch_script(
                parent_dramatic_state_out=parent_out,
                label=label or "继续",
                script=raw_script,
            )
            try:
                script = NodeScript.model_validate(sanitize_script_dict(grounded))
            except Exception:
                continue
            node = graph.nodes[nid]
            script_updates.append(
                {
                    "node_id": nid,
                    "script": script.model_dump(),
                    "title": node.title,
                    "summary": node.summary,
                }
            )
            modified = True
            continue

        if kind == "remove_branch":
            if remove_count >= _MAX_REMOVE_BRANCH_PER_ROUND:
                continue
            cannot_fix = str(act.get("cannot_fix_reason") or "").strip()
            if len(cannot_fix) < 8:
                continue
            fr = str(act.get("from_node_id") or "").strip()
            to = str(act.get("to_node_id") or "").strip()
            if not fr or not to:
                continue
            saved_options = list(graph.options)
            saved_edges = list(graph.edges)
            if not remove_branch_edge(graph, fr, to):
                continue
            after_paths = root_to_ending_path_count(graph)
            if after_paths < min_paths:
                graph.options = saved_options
                graph.edges = saved_edges
                repo.append_event(
                    story_id,
                    phase=FissionPhase.compliance,
                    type="log",
                    message=(
                        f"拒绝删边 {fr}→{to}：剧情线 {after_paths} < min_paths={min_paths}"
                    ),
                )
                continue
            remove_count += 1
            modified = True

    if modified:
        apply_layout(graph)
        repo.save_graph(graph)
        repo.append_event(
            story_id,
            phase=FissionPhase.compliance,
            type="graph",
            message=f"DAG 合规修复：{len(actions)} 项动作（删边 {remove_count}）",
            payload={
                "analysis": str(data.get("analysis") or "")[:500],
                "actions": actions[:20],
                "paths_before_after": {
                    "removed_edges": remove_count,
                },
            },
        )

    if script_updates:
        tools = FissionTools(story_id, repo=repo)
        result = tools.write_node_scripts(script_updates)
        parsed = json.loads(result)
        if not parsed.get("ok"):
            raise RuntimeError(parsed.get("error") or "write_node_scripts 失败")
        modified = True

    return modified
