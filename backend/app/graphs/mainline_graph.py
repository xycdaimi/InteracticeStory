from __future__ import annotations

import json
import re
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict

from backend.app.agents.fission_tools import FissionTools, _SCRIPT_JSON_SCHEMA
from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.ai.message_compat import dict_messages_to_lc, lc_response_to_openai
from backend.app.config import get_settings
from backend.app.models.enums import FissionPhase
from backend.app.models.story_graph import NodeScript
from backend.app.models.story_spine import StorySpine
from backend.app.services.graph_refs import mainline_spine_complete
from backend.app.services.story_repository import StoryRepository
from backend.app.services.story_spine_store import (
    completion_point_reached,
    load_story_spine,
    match_spine_event_index,
    validate_mainline_spine_coverage,
)


class MainlineOutlineNode(BaseModel):
    spine_event: str = Field(min_length=2)
    title: str = Field(min_length=1)
    summary: str = ""
    option_label: str = "继续"


class MainlinePlan(BaseModel):
    nodes: list[MainlineOutlineNode] = Field(min_length=1)


class MainlineGraphState(TypedDict, total=False):
    story_id: str
    outlines: list[dict[str, Any]]
    beats: list[dict[str, Any]]
    batch_idx: int
    total_batches: int
    prev_out: str
    error: str | None


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("模型返回空内容")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        data = json.loads(fence.group(1).strip())
        if isinstance(data, dict):
            return data
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data
    raise ValueError("无法解析 JSON")


from backend.app.services.script_sanitize import sanitize_script_dict


async def _lc_chat_text(messages: list[dict[str, Any]], *, model: str | None = None) -> str:
    llm = get_geekai_chat_model(model=model)
    resp = await llm.ainvoke(dict_messages_to_lc(messages))
    data = lc_response_to_openai(resp)
    return str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()


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
            return _extract_json_object(content)
        raise ValueError(f"模型未调用工具 {tool_name}")
    fn = tool_calls[0].get("function") or {}
    raw = fn.get("arguments") or "{}"
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _normalize_plan_nodes(
    nodes: list[MainlineOutlineNode], key_events: list[str]
) -> list[MainlineOutlineNode]:
    out: list[MainlineOutlineNode] = []
    for n in nodes:
        idx = match_spine_event_index(n.spine_event, key_events)
        spine_event = key_events[idx] if idx is not None else n.spine_event
        out.append(
            MainlineOutlineNode(
                spine_event=spine_event,
                title=n.title,
                summary=n.summary,
                option_label=n.option_label,
            )
        )
    return out


async def ensure_spine_node(state: MainlineGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    if mainline_spine_complete(repo.load_graph(story_id)):
        return {}
    if load_story_spine(story_id) is not None:
        return {}

    settings = get_settings()
    tools = FissionTools(story_id, repo=repo)
    meta = repo.load_meta(story_id)
    meta.phase = FissionPhase.mainline
    repo.save_meta(meta)

    repo.append_event(
        story_id,
        phase=FissionPhase.mainline,
        type="phase",
        message="主线 LangGraph：整理故事骨架…",
    )
    prompt = (
        "你是互动故事主编。把用户灵感整理为完整脉络骨架。\n"
        "只输出 JSON：\n"
        '{"protagonist":"主角","completion_point":"完成点",'
        '"key_events":["按时间顺序的关键事件，最后一项抵达完成点"]}\n'
        f"关键事件数量建议 {settings.mainline_min_spine_events}–15。\n"
        f"## 灵感\n{meta.inspiration}"
    )
    raw = await _lc_chat_text(
        [
            {"role": "system", "content": "只输出合法 JSON，不要 markdown 解释。"},
            {"role": "user", "content": prompt},
        ]
    )
    data = _extract_json_object(raw)
    result = tools.define_story_spine(
        protagonist=str(data.get("protagonist", "")),
        completion_point=str(data.get("completion_point", "")),
        key_events=[str(x) for x in data.get("key_events") or []],
    )
    parsed = json.loads(result)
    if not parsed.get("ok"):
        return {"error": parsed.get("error") or "define_story_spine 失败"}
    return {}


async def plan_nodes_node(state: MainlineGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    spine = load_story_spine(story_id)
    if spine is None:
        return {"error": "故事骨架缺失"}
    if state.get("outlines"):
        return {}

    meta = repo.load_meta(story_id)
    repo.append_event(
        story_id,
        phase=FissionPhase.mainline,
        type="phase",
        message="主线 LangGraph：规划全部可拍节点…",
    )
    events_block = "\n".join(f"{i + 1}. {ev}" for i, ev in enumerate(spine.key_events))
    base_prompt = (
        "规划整条主线（单链、此阶段勿分支）。\n"
        "- 每个关键事件至少 1 个节点，复杂事件可 2–3 个节点；\n"
        "- spine_event 必须照抄下方 key_events 原文（一字不差）；\n"
        "- option_label 是玩家进入该节点的台词/行动/意图，禁止写结果摘要。\n"
        "只输出 JSON：\n"
        '{"nodes":[{"spine_event":"…","title":"…","summary":"≤80字","option_label":"…"}]}\n'
        f"## 主角\n{spine.protagonist}\n"
        f"## 完成点\n{spine.completion_point}\n"
        f"## key_events\n{events_block}\n"
        f"## 灵感\n{meta.inspiration[:800]}"
    )
    last_err = ""
    for attempt in range(3):
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "只输出合法 JSON。"},
            {"role": "user", "content": base_prompt},
        ]
        if last_err:
            messages.append(
                {"role": "user", "content": f"上次校验失败：{last_err}。请修正后重试。"}
            )
        try:
            raw = await _lc_chat_text(messages)
            plan = MainlinePlan.model_validate(_extract_json_object(raw))
            nodes = _normalize_plan_nodes(plan.nodes, spine.key_events)
            refs = [n.spine_event for n in nodes]
            issues = validate_mainline_spine_coverage(
                refs, spine.key_events, finalize=True
            )
            if issues:
                raise ValueError("；".join(issues))
            if len(nodes) < len(spine.key_events):
                raise ValueError(
                    f"节点过少：至少 {len(spine.key_events)} 个（每关键事件至少 1 节点）"
                )
            repo.append_event(
                story_id,
                phase=FissionPhase.mainline,
                type="graph",
                message=f"主线 LangGraph：已规划 {len(nodes)} 个节点",
                payload={"node_count": len(nodes)},
            )
            settings = get_settings()
            batch_size = max(1, settings.mainline_script_batch_size)
            total_batches = (len(nodes) + batch_size - 1) // batch_size
            return {
                "outlines": [n.model_dump() for n in nodes],
                "beats": [],
                "batch_idx": 0,
                "total_batches": total_batches,
                "prev_out": meta.inspiration[:120],
            }
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)[:400]
    return {"error": f"节点规划失败：{last_err}"}


async def _script_batch_llm(
    *,
    batch: list[MainlineOutlineNode],
    spine: StorySpine,
    prev_state_out: str,
) -> list[NodeScript]:
    nodes_desc = json.dumps(
        [n.model_dump() for n in batch],
        ensure_ascii=False,
        indent=2,
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
                    "minItems": len(batch),
                    "maxItems": len(batch),
                    "items": script_item_schema,
                }
            },
            "required": ["scripts"],
        },
    }
    base_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你是舞台剧本作者。必须通过 submit_scripts 工具提交剧本。"
                "每个 script：duration_seconds 8；beats 至少 2 条且含 t_start/t_end/shot/action/dialogue；"
                "visual_plan.first_frame.depicts 必填；至少一句可听见对白。"
                "hidden_or_pov_only_ids 中的角色不得出现在 character_refs。"
                f"故事完成点：{spine.completion_point}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"上一节点离开状态：{prev_state_out or '（起点）'}\n"
                f"为以下 {len(batch)} 个节点写 script（顺序一致）：\n{nodes_desc}"
            ),
        },
    ]
    last_err = ""
    for attempt in range(3):
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
            if not isinstance(scripts_raw, list) or len(scripts_raw) != len(batch):
                raise ValueError(
                    f"剧本批次数量不符：期望 {len(batch)}，"
                    f"实际 {len(scripts_raw) if isinstance(scripts_raw, list) else 0}"
                )
            return [
                NodeScript.model_validate(sanitize_script_dict(s)) for s in scripts_raw
            ]
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)[:400]
    raise RuntimeError(f"剧本批次生成失败：{last_err}")


async def script_batch_node(state: MainlineGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    spine = load_story_spine(story_id)
    if spine is None:
        return {"error": "故事骨架缺失"}

    outlines = [MainlineOutlineNode.model_validate(o) for o in state.get("outlines") or []]
    batch_idx = int(state.get("batch_idx") or 0)
    settings = get_settings()
    batch_size = max(1, settings.mainline_script_batch_size)
    start = batch_idx * batch_size
    batch = outlines[start : start + batch_size]
    if not batch:
        return {"batch_idx": batch_idx}

    repo.append_event(
        story_id,
        phase=FissionPhase.mainline,
        type="log",
        message=(
            f"主线 LangGraph：剧本化 {batch_idx + 1}/"
            f"{state.get('total_batches', 1)}（{len(batch)} 节点）…"
        ),
    )
    try:
        scripts = await _script_batch_llm(
            batch=batch,
            spine=spine,
            prev_state_out=str(state.get("prev_out") or ""),
        )
    except RuntimeError as exc:
        return {"error": str(exc)}

    beats = list(state.get("beats") or [])
    prev_out = str(state.get("prev_out") or "")
    for outline, script in zip(batch, scripts, strict=True):
        beats.append(
            {
                "spine_event": outline.spine_event,
                "title": outline.title,
                "summary": outline.summary,
                "option_label": outline.option_label,
                "script": script.model_dump(),
            }
        )
        prev_out = script.dramatic_state_out

    return {
        "beats": beats,
        "batch_idx": batch_idx + 1,
        "prev_out": prev_out,
    }


async def write_mainline_node(state: MainlineGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    if mainline_spine_complete(repo.load_graph(story_id)):
        return {}

    beats = state.get("beats") or []
    if not beats:
        return {"error": "无主线节点可写入"}

    spine = load_story_spine(story_id)
    if spine is not None:
        last_script = dict(beats[-1].get("script") or {})
        out = str(last_script.get("dramatic_state_out") or "")
        if not completion_point_reached(spine, out):
            cp = spine.completion_point.strip()
            last_script["dramatic_state_out"] = f"{out}——{cp}"[:240]
            beats[-1] = {**beats[-1], "script": last_script}

    tools = FissionTools(story_id, repo=repo)
    result = tools.write_mainline(beats, finalize=True)
    parsed = json.loads(result)
    if not parsed.get("ok"):
        return {"error": parsed.get("error") or "write_mainline 失败"}

    repo.append_event(
        story_id,
        phase=FissionPhase.mainline,
        type="graph",
        message=parsed.get("next") or "主线已写入",
        payload={"mainline_complete": True, "node_count": len(beats)},
    )
    return {}


def _route_after_plan(state: MainlineGraphState) -> Literal["script_batch", "fail", "write"]:
    if state.get("error"):
        return "fail"
    if state.get("outlines") and not state.get("beats") and state.get("batch_idx", 0) == 0:
        return "script_batch"
    return "write"


def _route_after_batch(state: MainlineGraphState) -> Literal["script_batch", "write", "fail"]:
    if state.get("error"):
        return "fail"
    outlines = state.get("outlines") or []
    settings = get_settings()
    batch_size = max(1, settings.mainline_script_batch_size)
    total_batches = (len(outlines) + batch_size - 1) // batch_size
    if int(state.get("batch_idx") or 0) < total_batches:
        return "script_batch"
    return "write"


def _route_after_spine(state: MainlineGraphState) -> Literal["plan", "write", "fail"]:
    if state.get("error"):
        return "fail"
    story_id = state["story_id"]
    if mainline_spine_complete(StoryRepository().load_graph(story_id)):
        return "write"
    return "plan"


def build_mainline_graph():
    g = StateGraph(MainlineGraphState)
    g.add_node("ensure_spine", ensure_spine_node)
    g.add_node("plan", plan_nodes_node)
    g.add_node("script_batch", script_batch_node)
    g.add_node("write", write_mainline_node)

    def fail_node(state: MainlineGraphState) -> dict[str, Any]:
        return {"error": state.get("error") or "主线失败"}

    g.add_node("fail", fail_node)

    g.add_edge(START, "ensure_spine")
    g.add_conditional_edges(
        "ensure_spine",
        _route_after_spine,
        {"plan": "plan", "write": "write", "fail": "fail"},
    )
    g.add_conditional_edges(
        "plan",
        _route_after_plan,
        {"script_batch": "script_batch", "write": "write", "fail": "fail"},
    )
    g.add_conditional_edges(
        "script_batch",
        _route_after_batch,
        {"script_batch": "script_batch", "write": "write", "fail": "fail"},
    )
    g.add_edge("write", END)
    g.add_edge("fail", END)
    return g.compile()


async def run_mainline_graph(story_id: str) -> None:
    if mainline_spine_complete(StoryRepository().load_graph(story_id)):
        return
    graph = build_mainline_graph()
    final = await graph.ainvoke({"story_id": story_id})
    if final.get("error"):
        raise RuntimeError(final["error"])
