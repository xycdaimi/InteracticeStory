from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any

from pydantic import ValidationError

from backend.app.agents.branch_script_prompts import (
    SYSTEM,
    build_branch_script_batch_prompt,
)
from backend.app.agents.fission_tools import FissionTools, _SCRIPT_JSON_SCHEMA
from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.ai.message_compat import dict_messages_to_lc, lc_response_to_openai
from backend.app.config import get_settings
from backend.app.models.enums import FissionPhase, NodeKind
from backend.app.models.story_graph import NodeScript
from backend.app.services.plot_tree_store import load_plot_tree
from backend.app.services.script_sanitize import sanitize_script_dict
from backend.app.services.story_repository import StoryRepository
from backend.app.services.story_spine_store import load_story_spine


async def _lc_chat_tool_args(
    *,
    messages: list[dict[str, Any]],
    tool_name: str,
    tool_schema: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    fn_schema = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_schema.get("description", ""),
            "parameters": tool_schema.get("parameters", tool_schema),
        },
    }
    llm = get_geekai_chat_model(model=model).bind_tools(
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


def _missing_script_layers(graph) -> list[list[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for opt in graph.options:
        children[opt.from_node_id].append(opt.to_node_id)

    bucket: dict[int, list[str]] = defaultdict(list)
    q: deque[tuple[str, int]] = deque([(graph.root_id, 0)])
    seen: set[str] = {graph.root_id}
    while q:
        nid, depth = q.popleft()
        if nid != graph.root_id:
            node = graph.nodes[nid]
            if node.script is None:
                bucket[depth].append(nid)
        for child in children.get(nid) or []:
            if child not in seen:
                seen.add(child)
                q.append((child, depth + 1))
    return [bucket[d] for d in sorted(bucket) if bucket[d]]


def _option_label_for(graph, node_id: str) -> str:
    for opt in graph.options:
        if opt.to_node_id == node_id:
            return opt.label
    return "继续"


def _parent_hint(graph, node_id: str) -> dict[str, str]:
    node = graph.nodes[node_id]
    parent = graph.nodes.get(node.parent_id) if node.parent_id else None
    if parent is None:
        return {"dramatic_state_out": "", "summary": "", "title": ""}
    out = parent.script.dramatic_state_out if parent.script else ""
    return {
        "dramatic_state_out": out,
        "summary": parent.summary or "",
        "title": parent.title or "",
    }


async def _write_batch_scripts(
    *,
    batch_ids: list[str],
    graph,
    story_state,
    completion_point: str,
) -> list[dict[str, Any]]:
    batch_nodes = []
    parent_hints: dict[str, dict] = {}
    for nid in batch_ids:
        node = graph.nodes[nid]
        batch_nodes.append(
            {
                "node_id": nid,
                "title": node.title,
                "summary": node.summary,
                "option_label": _option_label_for(graph, nid),
                "kind": node.kind.value,
                "outcome": node.outcome,
                "spine_event": node.spine_event,
            }
        )
        parent_hints[nid] = _parent_hint(graph, nid)

    user_prompt = build_branch_script_batch_prompt(
        batch_nodes=batch_nodes,
        story_state=story_state,
        parent_hints=parent_hints,
        completion_point=completion_point,
    )
    script_item_schema = {
        "type": "object",
        "required": [
            "duration_seconds",
            "dramatic_state_in",
            "dramatic_state_out",
            "beats",
            "visual_plan",
        ],
        "properties": _SCRIPT_JSON_SCHEMA["properties"],
    }
    tool_schema = {
        "description": "提交本批节点的完整 script，顺序与输入 nodes 一致",
        "parameters": {
            "type": "object",
            "properties": {
                "scripts": {
                    "type": "array",
                    "minItems": len(batch_ids),
                    "maxItems": len(batch_ids),
                    "items": script_item_schema,
                }
            },
            "required": ["scripts"],
        },
    }
    base_messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    last_err = ""
    for _attempt in range(3):
        messages = list(base_messages)
        if last_err:
            messages.append(
                {
                    "role": "user",
                    "content": f"上次校验失败：{last_err}。请严格按 schema 重试。",
                }
            )
        try:
            data = await _lc_chat_tool_args(
                messages=messages,
                tool_name="submit_scripts",
                tool_schema=tool_schema,
            )
            scripts_raw = data.get("scripts")
            if not isinstance(scripts_raw, list) or len(scripts_raw) != len(batch_ids):
                raise ValueError(
                    f"剧本批次数量不符：期望 {len(batch_ids)}，"
                    f"实际 {len(scripts_raw) if isinstance(scripts_raw, list) else 0}"
                )
            scripts = [
                NodeScript.model_validate(sanitize_script_dict(s)) for s in scripts_raw
            ]
            return [
                {
                    "node_id": nid,
                    "script": script.model_dump(),
                    "title": graph.nodes[nid].title,
                    "summary": graph.nodes[nid].summary,
                }
                for nid, script in zip(batch_ids, scripts, strict=True)
            ]
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)[:400]
    raise RuntimeError(f"分支剧本批次失败：{last_err}")


async def run_branch_script_graph(story_id: str) -> None:
    """Pass3：按 BFS 层批量为所有缺 script 的非 root 节点写剧本。"""
    repo = StoryRepository()
    meta = repo.load_meta(story_id)
    spine = load_story_spine(story_id)
    if spine is None:
        raise RuntimeError("缺少 story spine")
    _ = load_plot_tree(story_id)

    meta.phase = FissionPhase.branch_script
    repo.save_meta(meta)
    repo.append_event(
        story_id,
        phase=FissionPhase.branch_script,
        type="phase",
        message="Pass3：按层批量写节点剧本",
    )

    settings = get_settings()
    batch_size = max(1, settings.mainline_script_batch_size)
    tools = FissionTools(story_id, repo=repo)

    graph = repo.load_graph(story_id)
    layers = _missing_script_layers(graph)
    for layer_idx, layer in enumerate(layers):
        for i in range(0, len(layer), batch_size):
            batch_ids = layer[i : i + batch_size]
            graph = repo.load_graph(story_id)
            state = repo.ensure_story_state(story_id)
            repo.append_event(
                story_id,
                phase=FissionPhase.branch_script,
                type="log",
                message=(
                    f"剧本层 {layer_idx + 1}/{len(layers)} "
                    f"批次 {i // batch_size + 1}（{len(batch_ids)} 节点）"
                ),
            )
            updates = await _write_batch_scripts(
                batch_ids=batch_ids,
                graph=graph,
                story_state=state,
                completion_point=spine.completion_point,
            )
            result = tools.write_node_scripts(updates)
            parsed = json.loads(result)
            if not parsed.get("ok"):
                raise RuntimeError(parsed.get("error") or "write_node_scripts 失败")

            graph = repo.load_graph(story_id)
            for item in updates:
                nid = item["node_id"]
                node = graph.nodes.get(nid)
                if node and node.script:
                    state = state.with_dramatic_state(node.script.dramatic_state_out)
                    if node.summary:
                        state = state.add_fact(node.summary[:120])
            repo.save_story_state(story_id, state)

    graph = repo.load_graph(story_id)
    missing = [
        nid
        for nid, n in graph.nodes.items()
        if nid != graph.root_id and n.script is None
    ]
    if missing:
        raise RuntimeError(f"仍有非 root 节点缺少 script: {missing[:20]}")

    endings_without = [
        nid
        for nid, n in graph.nodes.items()
        if n.kind == NodeKind.ending and not n.outcome
    ]
    if endings_without:
        raise RuntimeError(f"ending 节点缺少 outcome: {endings_without[:20]}")

    repo.append_event(
        story_id,
        phase=FissionPhase.branch_script,
        type="phase",
        message="Pass3 节点剧本全部写完",
        payload={"node_count": len(graph.nodes)},
    )
