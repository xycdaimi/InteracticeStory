from __future__ import annotations

import json
import re
from typing import Any

from backend.app.agents.fission_tools import FissionTools
from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.ai.message_compat import dict_messages_to_lc, lc_response_to_openai
from backend.app.models.enums import FissionPhase
from backend.app.models.fission_config import FissionConfig
from backend.app.models.plot_tree import PlotTreeOutline
from backend.app.services.plot_tree_repair import (
    _plot_tree_hard_constraints,
    analyze_plot_tree_issues,
    build_plot_tree_repair_prompt,
    plot_tree_generation_fork_guide,
)
from backend.app.services.plot_tree_store import save_plot_tree
from backend.app.services.plot_tree_validate import normalize_plot_tree_outline, validate_plot_tree
from backend.app.services.story_repository import StoryRepository
from backend.app.services.story_spine_store import load_story_spine

_MAX_PLOT_TREE_ROUNDS = 8


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


async def _lc_chat_text(messages: list[dict[str, Any]], *, model: str | None = None) -> str:
    llm = get_geekai_chat_model(model=model)
    resp = await llm.ainvoke(dict_messages_to_lc(messages))
    data = lc_response_to_openai(resp)
    return str(
        (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    ).strip()


def _build_plot_tree_prompt(
    *,
    inspiration: str,
    protagonist: str,
    completion_point: str,
    key_events: list[str],
    config: FissionConfig,
) -> str:
    et = config.ending_targets
    events_block = "\n".join(f"{i + 1}. {ev}" for i, ev in enumerate(key_events))
    return (
        "你是互动故事结构编剧。只输出剧情树纯结构 JSON，禁止任何 script/对白正文。\n"
        "Schema：\n"
        "{\n"
        '  "root": "S01",\n'
        '  "nodes": [\n'
        '    {"id":"S01","type":"start","title":"…","summary":"≤80字",'
        '"spine_event":"…","option_label":"继续","tags":[],"parent":null},\n'
        '    {"id":"S02A","type":"branch","title":"…","summary":"对峙点：可偷听/硬闯/合作",'
        '"parent":"S01","fork_slot":"method","option_label":"「具体台词」","tags":["悬疑"]},\n'
        '    {"id":"S02B","type":"branch","title":"…","summary":"同一对峙点：选择信任引路人",'
        '"parent":"S01","fork_slot":"stance","option_label":"「跟他走」","tags":["悬疑"]},\n'
        '    {"id":"END1","type":"ending","title":"…","parent":"S02A",'
        '"outcome":"completed","option_label":"「…」","tags":[]}\n'
        "  ],\n"
        '  "edges": [{"from":"S01","to":"S02A","label":"「具体台词」"}]\n'
        "}\n"
        "硬约束：\n"
        + _plot_tree_hard_constraints(config)
        + plot_tree_generation_fork_guide()
        + "\n"
        "- 主脉络节点须带 spine_event（对照 key_events），type 可用 merge；"
        "纯岔路用 type=branch\n"
        "- start 无 parent/入边；ending 无出边；无孤立；非 ending 必须可达 ending\n"
        "- nodes 可带 tags（悬疑/恋爱/战斗/选择/反转/真相）\n"
        "- type ∈ start|branch|merge|ending；merge 可用 rejoin 指向汇合点\n"
        "- spine_event 尽量对照下方关键事件原文\n"
        f"## 主角\n{protagonist}\n"
        f"## 完成点\n{completion_point}\n"
        f"## key_events\n{events_block}\n"
        f"## 灵感\n{inspiration[:800]}\n"
        f"## 风格\n{config.style_tags}\n"
        f"## 结局分布建议\n"
        f"completed≈{et.completed} near≈{et.near} failed≈{et.failed}\n"
    )


def _outline_to_assistant_json(outline: PlotTreeOutline) -> str:
    return json.dumps(
        outline.model_dump(by_alias=True),
        ensure_ascii=False,
        indent=2,
    )


def _parse_outline_payload(data: dict[str, Any]) -> PlotTreeOutline:
    for n in data.get("nodes") or []:
        if isinstance(n, dict):
            n.pop("script", None)
    return PlotTreeOutline.model_validate(data)


async def run_plot_tree_graph(story_id: str) -> None:
    """Pass2：LLM 产出 PlotTreeOutline → 结构校验 → 剧情驱动迭代修复 → apply。"""
    repo = StoryRepository()
    meta = repo.load_meta(story_id)
    config = repo.ensure_fission_config(story_id)
    spine = load_story_spine(story_id)
    if spine is None:
        raise RuntimeError("缺少 story spine，请先完成 story_bible")

    meta.phase = FissionPhase.plot_tree
    repo.save_meta(meta)
    repo.append_event(
        story_id,
        phase=FissionPhase.plot_tree,
        type="phase",
        message="Pass2：生成剧情树结构",
    )

    base_prompt = _build_plot_tree_prompt(
        inspiration=meta.inspiration,
        protagonist=spine.protagonist,
        completion_point=spine.completion_point,
        key_events=list(spine.key_events),
        config=config,
    )

    system_msg = {
        "role": "system",
        "content": (
            "只输出合法 JSON（PlotTreeOutline），禁止 script。"
            "非 ending 节点必须填分叉槽位（≥2 条选择出边、≥2 个 fork_slot 维度），"
            "禁止顺滑单链。"
        ),
    }
    messages: list[dict[str, Any]] = [
        system_msg,
        {"role": "user", "content": base_prompt},
    ]

    last_err = ""
    outline: PlotTreeOutline | None = None

    for round_idx in range(_MAX_PLOT_TREE_ROUNDS):
        try:
            raw = await _lc_chat_text(messages)
            data = _extract_json_object(raw)
            outline = _parse_outline_payload(data)
            outline = normalize_plot_tree_outline(outline)
            errs = validate_plot_tree(outline, config)
            if not errs:
                if round_idx > 0:
                    repo.append_event(
                        story_id,
                        phase=FissionPhase.plot_tree,
                        type="graph",
                        message=f"剧情树结构修复完成（第 {round_idx + 1} 轮）",
                        payload={"repair_rounds": round_idx},
                    )
                break

            last_err = "；".join(errs)[:1200]
            if round_idx + 1 >= _MAX_PLOT_TREE_ROUNDS:
                raise ValueError(last_err)

            analysis = analyze_plot_tree_issues(outline, config)
            slot_focus = len(analysis.get("single_choice_nodes") or []) > 0
            repair_prompt = build_plot_tree_repair_prompt(
                outline=outline,
                errors=errs,
                config=config,
                protagonist=spine.protagonist,
                completion_point=spine.completion_point,
                key_events=list(spine.key_events),
                slot_focus=slot_focus and round_idx >= 1,
            )
            repo.append_event(
                story_id,
                phase=FissionPhase.plot_tree,
                type="graph",
                message=f"剧情树结构校验未通过，启动第 {round_idx + 2} 轮剧情修复",
                payload={"errors": errs[:8], "round": round_idx + 1},
            )
            messages = [
                system_msg,
                {"role": "user", "content": base_prompt},
                {"role": "assistant", "content": _outline_to_assistant_json(outline)},
                {"role": "user", "content": repair_prompt},
            ]
        except Exception as exc:
            last_err = str(exc)[:1200]
            outline = None
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"输出无法使用：{last_err}\n请只输出修正后的 PlotTreeOutline JSON。"
                    ),
                }
            )

    if outline is None:
        raise RuntimeError(f"plot_tree 生成失败：{last_err}")

    final_errs = validate_plot_tree(outline, config)
    if final_errs:
        raise RuntimeError(f"plot_tree 生成失败：{'；'.join(final_errs)[:800]}")

    tools = FissionTools(story_id, repo=repo)
    result = tools.apply_plot_tree(outline.model_dump(by_alias=True))
    parsed = json.loads(result)
    if not parsed.get("ok"):
        raise RuntimeError(parsed.get("error") or "apply_plot_tree 失败")

    save_plot_tree(story_id, outline)
    repo.append_event(
        story_id,
        phase=FissionPhase.plot_tree,
        type="graph",
        message=f"Pass2 剧情树完成：{parsed.get('node_count')} 节点",
        payload={
            "node_count": parsed.get("node_count"),
            "edge_count": parsed.get("edge_count"),
        },
    )
