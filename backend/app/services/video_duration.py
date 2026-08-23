from __future__ import annotations

import json
import re
from typing import Any

from backend.app.infrastructure.paths import shot_prompt_path
from backend.app.models.story_graph import StoryGraph

MIN_DURATION = 4
MAX_DURATION = 15


def clamp_duration(seconds: int) -> int:
    return max(MIN_DURATION, min(MAX_DURATION, int(seconds)))


def infer_duration_from_content(
    *,
    title: str = "",
    summary: str = "",
    prompt_text: str = "",
    node_kind: str | None = None,
    first_frame_source: str | None = None,
) -> int:
    """根据剧情密度、镜头节奏与衔接方式估算片段时长（秒）。"""
    text = f"{title} {summary} {prompt_text}"
    char_count = len(text.strip())

    if first_frame_source == "prev_last_frame":
        base = 5
    else:
        base = 7

    kind = (node_kind or "").lower()
    if kind == "ending":
        base = max(base, 9)
    elif kind in ("root", "main"):
        base = max(base, 7)

    if char_count > 220:
        base += 3
    elif char_count > 140:
        base += 2
    elif char_count > 80:
        base += 1

    dialogue = text.count("：") + text.count(":") + text.count("「") + text.count("」")
    if dialogue >= 3:
        base += 2
    elif dialogue >= 1:
        base += 1

    beats = sum(
        text.count(marker)
        for marker in ("然后", "接着", "随后", "同时", "镜头", "切至", "；")
    )
    base += min(beats, 3)

    action_markers = ("奔跑", "打斗", "爆炸", "追逐", "交战", "呐喊", "群", "大军")
    if any(m in text for m in action_markers):
        base += 1

    return clamp_duration(base)


def parse_shot_prompt_response(
    raw: str,
    *,
    title: str = "",
    summary: str = "",
    node_kind: str | None = None,
    first_frame_source: str | None = None,
) -> tuple[str, int]:
    """解析 LLM 返回的 JSON；纯文本时回退为全文提示词 + 启发式时长。"""
    text = raw.strip()
    if not text:
        raise ValueError("empty shot prompt response")

    payload = text
    if text.startswith("```"):
        payload = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        payload = re.sub(r"\s*```$", "", payload).strip()

    try:
        data = json.loads(payload)
        prompt_text = (data.get("prompt_text") or "").strip()
        if not prompt_text:
            raise ValueError("missing prompt_text")
        raw_dur = data.get("duration_seconds")
        if raw_dur is None:
            duration = infer_duration_from_content(
                title=title,
                summary=summary,
                prompt_text=prompt_text,
                node_kind=node_kind,
                first_frame_source=first_frame_source,
            )
        else:
            duration = clamp_duration(int(raw_dur))
        return prompt_text, duration
    except (json.JSONDecodeError, TypeError, ValueError):
        prompt_text = text
        duration = infer_duration_from_content(
            title=title,
            summary=summary,
            prompt_text=prompt_text,
            node_kind=node_kind,
            first_frame_source=first_frame_source,
        )
        return prompt_text, duration


def resolve_segment_duration(
    segment: dict[str, Any],
    shot_doc: dict[str, Any],
    *,
    title: str = "",
    summary: str = "",
    node_kind: str | None = None,
) -> int:
    for key in ("video_duration",):
        if segment.get(key):
            return clamp_duration(int(segment[key]))
    if shot_doc.get("duration_seconds"):
        return clamp_duration(int(shot_doc["duration_seconds"]))
    return infer_duration_from_content(
        title=title,
        summary=summary,
        prompt_text=shot_doc.get("prompt_text") or "",
        node_kind=node_kind,
        first_frame_source=segment.get("first_frame_source"),
    )


def sync_segment_durations(
    story_id: str,
    blueprint: dict[str, Any],
    graph: StoryGraph,
    *,
    persist_shot_files: bool = True,
) -> int:
    """为 blueprint 中各 segment 补齐 video_duration，必要时回写 shot prompt 文件。"""
    node_by_id = {n["node_id"]: n for n in blueprint.get("nodes", [])}
    updated = 0

    for seg in blueprint.get("segments") or []:
        nid = seg.get("prompt_node_id")
        if not nid:
            continue

        path = shot_prompt_path(story_id, nid)
        shot_doc: dict[str, Any] = {}
        if path.exists():
            try:
                shot_doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                shot_doc = {}

        g_node = graph.nodes.get(nid)
        bp_node = node_by_id.get(nid, {})
        title = bp_node.get("title") or (g_node.title if g_node else "")
        summary = bp_node.get("summary") or (g_node.summary if g_node else "")
        node_kind = g_node.kind.value if g_node else bp_node.get("kind")

        duration = resolve_segment_duration(
            seg,
            shot_doc,
            title=title,
            summary=summary,
            node_kind=node_kind,
        )

        changed = seg.get("video_duration") != duration
        seg["video_duration"] = duration
        if shot_doc.get("duration_seconds") != duration:
            shot_doc["duration_seconds"] = duration
            if persist_shot_files and shot_doc.get("prompt_text") and path.exists():
                path.write_text(
                    json.dumps(shot_doc, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            changed = True

        if changed:
            updated += 1

    return updated
