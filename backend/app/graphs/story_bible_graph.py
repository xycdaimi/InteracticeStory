from __future__ import annotations

import json
import re
from typing import Any

from backend.app.agents.fission_tools import FissionTools
from backend.app.agents.story_bible_prompts import SYSTEM, build_story_bible_prompt
from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.ai.message_compat import dict_messages_to_lc, lc_response_to_openai
from backend.app.models.enums import FissionPhase
from backend.app.models.fission_config import CharacterConfig, StoryStateTable
from backend.app.services.story_repository import StoryRepository


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


async def run_story_bible_graph(story_id: str) -> None:
    """Pass1：世界观/角色/冲突/关键事件 → define_story_spine + 初始化状态表。"""
    repo = StoryRepository()
    meta = repo.load_meta(story_id)
    config = repo.ensure_fission_config(story_id, inspiration=meta.inspiration)
    repo.ensure_story_state(story_id)

    meta.phase = FissionPhase.bible
    repo.save_meta(meta)
    repo.append_event(
        story_id,
        phase=FissionPhase.bible,
        type="phase",
        message="Pass1：生成故事总纲（bible）",
    )

    prompt = build_story_bible_prompt(inspiration=meta.inspiration, config=config)
    last_err = ""
    data: dict[str, Any] | None = None
    for _attempt in range(3):
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ]
        if last_err:
            messages.append(
                {
                    "role": "user",
                    "content": f"上次失败：{last_err}。请修正后只输出 JSON。",
                }
            )
        try:
            raw = await _lc_chat_text(messages)
            data = _extract_json_object(raw)
            key_events = [
                str(x).strip() for x in (data.get("key_events") or []) if str(x).strip()
            ]
            if len(key_events) < 6:
                raise ValueError(f"key_events 至少 6 项，当前 {len(key_events)}")
            protagonist = str(data.get("protagonist") or "").strip()
            completion = str(data.get("completion_point") or "").strip()
            if not protagonist or not completion:
                raise ValueError("缺少 protagonist 或 completion_point")
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)[:400]
            data = None
    if data is None:
        raise RuntimeError(f"story_bible 生成失败：{last_err}")

    tools = FissionTools(story_id, repo=repo)
    result = tools.define_story_spine(
        protagonist=str(data.get("protagonist") or ""),
        completion_point=str(data.get("completion_point") or ""),
        key_events=[str(x) for x in data.get("key_events") or []],
    )
    parsed = json.loads(result)
    if not parsed.get("ok"):
        raise RuntimeError(parsed.get("error") or "define_story_spine 失败")

    chars_raw = data.get("characters") or []
    new_chars: list[CharacterConfig] = []
    if isinstance(chars_raw, list):
        for c in chars_raw:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "").strip()
            name = str(c.get("name") or "").strip()
            if not cid or not name:
                continue
            traits = [str(t) for t in (c.get("traits") or []) if str(t).strip()]
            state_keys = [
                str(k)
                for k in (c.get("state_keys") or c.get("states") or [])
                if str(k).strip()
            ]
            new_chars.append(
                CharacterConfig(
                    id=cid, name=name, traits=traits, state_keys=state_keys
                )
            )
    if new_chars:
        config = config.model_copy(update={"characters": new_chars})
        repo.save_fission_config(story_id, config)

    player_state: dict[str, int | bool | str] = {}
    for ch in config.characters:
        for key in ch.state_keys:
            player_state[f"{ch.id}_{key}"] = 50

    facts = [
        x
        for x in [
            str(data.get("worldview") or "").strip(),
            str(data.get("core_conflict") or "").strip(),
        ]
        if x
    ]
    state = StoryStateTable(
        chapter=1,
        player_state=player_state,
        story_facts=facts,
        dramatic_state="",
    )
    repo.save_story_state(story_id, state)

    endings = data.get("ending_directions") or []
    repo.append_context(
        story_id,
        "\n".join(
            [
                "## Story Bible",
                f"worldview: {data.get('worldview', '')}",
                f"protagonist: {data.get('protagonist', '')}",
                f"core_conflict: {data.get('core_conflict', '')}",
                f"completion_point: {data.get('completion_point', '')}",
                f"ending_directions: {endings}",
            ]
        ),
    )
    repo.append_event(
        story_id,
        phase=FissionPhase.bible,
        type="phase",
        message="Pass1 总纲完成",
        payload={
            "event_count": parsed.get("event_count"),
            "character_count": len(config.characters),
        },
    )
