from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.ai.geekai_client import GeekAIClient
from backend.app.config import get_settings
from backend.app.infrastructure.paths import story_dir
from backend.app.models.enums import FissionPhase
from backend.app.models.story_graph import StoryGraph
from backend.app.services.compliance import extract_json_object
from backend.app.services.play_context import incoming_choice
from backend.app.services.segment_plan import derive_first_frame_source
from backend.app.services.story_repository import StoryRepository

SHOT_CONTINUITY_SYSTEM = """你是互动短剧剪辑指导。只输出 JSON，不要 markdown。

## 任务
判断：玩家看完【上一节点】视频后，【本节点】视频是否应直接承接上一段视频的末帧作为首帧（同一连续镜头、无硬切）。

注意：系统已在代码中处理「跨场景」「线首」「多前驱」等情况；你只对剩余边做语义判断。
同地点也可切镜、跳时 → continues=false。

## continues=true 当且仅当
- 时间紧接、同一连续动作/对白/运镜，观众感受「镜头没断」
- 上一段末帧的人物位置、景别可直接作为本段开场

## continues=false 当
- 硬切、新景别建立、反应镜头、插入镜头、回忆、梦境、时间跳跃、视角突变
- 不确定 → false

## 输出
{"edges":[{"from_node_id":"节点ID","to_node_id":"节点ID","continues":true|false,"reason":"…"}]}
from_node_id / to_node_id 必须是故事图节点 ID（如 n_abc），禁止填 segment_id（seg_ 开头）。
必须覆盖输入中每条边。"""

_BATCH_SIZE = 40


@dataclass
class EdgeContinuityInput:
    segment_id: str
    from_node_id: str
    to_node_id: str
    pred_segment_id: str | None
    option_label: str
    from_title: str
    from_summary: str
    to_title: str
    to_summary: str


def apply_hard_rules(
    segment: dict[str, Any],
    graph: StoryGraph,
    segments_by_id: dict[str, dict[str, Any]],
) -> tuple[bool, str | None]:
    """返回 (blocked, reason_code)。blocked=True 表示层 0 否决，continues 必 false。"""
    if segment.get("from_is_root") or segment.get("from_node_id") == graph.root_id:
        return True, "ROOT_EDGE"
    preds = segment.get("pred_candidate_ids") or []
    if len(preds) > 1:
        return True, "MULTI_PRED"
    if not segment.get("pred_segment_id"):
        return True, "NO_PRED"
    pred_id = segment["pred_segment_id"]
    if pred_id not in segments_by_id:
        return True, "MISSING_PRED_SEG"
    from_node = graph.nodes.get(segment["from_node_id"])
    to_node = graph.nodes.get(segment["to_node_id"])
    from_scene = from_node.scene_id if from_node else None
    to_scene = to_node.scene_id if to_node else None
    if from_scene and to_scene and from_scene != to_scene:
        return True, "CROSS_SCENE"
    return False, None


def _edge_key(from_node_id: str, to_node_id: str) -> str:
    return f"{from_node_id}|{to_node_id}"


def _option_label(graph: StoryGraph, segment: dict[str, Any]) -> str:
    oid = segment.get("option_id")
    if oid:
        for opt in graph.options:
            if opt.id == oid:
                return opt.label
    label, _, _ = incoming_choice(graph, segment["to_node_id"])
    return label or "（主线推进）"


def collect_edges_for_annotation(
    graph: StoryGraph,
    segments: list[dict[str, Any]],
) -> list[EdgeContinuityInput]:
    segments_by_id = {s["segment_id"]: s for s in segments}
    edges: list[EdgeContinuityInput] = []
    seen: set[str] = set()
    for seg in segments:
        blocked, _ = apply_hard_rules(seg, graph, segments_by_id)
        if blocked:
            continue
        key = _edge_key(seg["from_node_id"], seg["to_node_id"])
        if key in seen:
            continue
        seen.add(key)
        from_node = graph.nodes.get(seg["from_node_id"])
        to_node = graph.nodes.get(seg["to_node_id"])
        edges.append(
            EdgeContinuityInput(
                segment_id=seg["segment_id"],
                from_node_id=seg["from_node_id"],
                to_node_id=seg["to_node_id"],
                pred_segment_id=seg.get("pred_segment_id"),
                option_label=_option_label(graph, seg),
                from_title=from_node.title if from_node else "",
                from_summary=(from_node.summary or "")[:200] if from_node else "",
                to_title=to_node.title if to_node else "",
                to_summary=(to_node.summary or "")[:200] if to_node else "",
            )
        )
    return edges


def build_shot_continuity_user(inspiration: str, edges: list[EdgeContinuityInput]) -> str:
    blocks = [f"故事灵感：{inspiration}", "请判断下列每条边的镜头是否连续承接："]
    for idx, edge in enumerate(edges):
        pred = edge.pred_segment_id or "无"
        blocks.append(
            f"\n--- 边 {idx} ---\n"
            f"from_node_id: {edge.from_node_id}\n"
            f"to_node_id: {edge.to_node_id}\n"
            f"segment_id（仅参考，勿写入输出）: {edge.segment_id}\n"
            f"玩家选项: {edge.option_label}\n"
            f"上一节点「{edge.from_title}」: {edge.from_summary}\n"
            f"本节点「{edge.to_title}」: {edge.to_summary}\n"
            f"前驱视频片段 ID: {pred}"
        )
    blocks.append("\n只返回 JSON 对象，edges 必须覆盖上述全部边。")
    return "\n".join(blocks)


def parse_shot_continuity_response(
    raw: str,
) -> dict[tuple[str, str], tuple[bool, str]]:
    payload = extract_json_object(raw)
    result: dict[tuple[str, str], tuple[bool, str]] = {}
    for item in payload.get("edges") or []:
        fid = item.get("from_node_id")
        tid = item.get("to_node_id")
        if not fid or not tid:
            continue
        result[(fid, tid)] = (bool(item.get("continues")), str(item.get("reason") or ""))
    return result


def lookup_llm_edge_result(
    parsed: dict[tuple[str, str], tuple[bool, str]],
    edge: EdgeContinuityInput,
) -> tuple[bool, str]:
    key = (edge.from_node_id, edge.to_node_id)
    if key in parsed:
        return parsed[key]
    for (fid, tid), val in parsed.items():
        if fid == edge.from_node_id and tid == edge.to_node_id:
            return val
        if tid == edge.segment_id or fid == edge.segment_id:
            return val
    return False, "LLM_OMIT"


def continuity_cache_path(story_id: str) -> Path:
    return story_dir(story_id) / "shot_continuity.json"


def graph_revision(graph: StoryGraph) -> str:
    return f"n{len(graph.nodes)}_o{len(graph.options)}"


def load_continuity_cache(story_id: str) -> dict[str, Any]:
    path = continuity_cache_path(story_id)
    if not path.is_file():
        return {"version": 1, "graph_revision": "", "edges": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_continuity_cache(story_id: str, cache: dict[str, Any]) -> None:
    path = continuity_cache_path(story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_continuity_to_segment(
    seg: dict[str, Any],
    *,
    continues: bool,
    reason: str,
) -> None:
    seg["continues_from_prev_shot"] = continues
    seg["continuity_reason"] = reason
    seg["first_frame_source"] = derive_first_frame_source(seg)


async def annotate_shot_continuity(
    story_id: str,
    graph: StoryGraph,
    plot_lines: list[Any],
    segments: list[dict[str, Any]],
    *,
    repo: StoryRepository | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    del plot_lines  # 边已全局去重，不按 plot_line 重复标注
    repo = repo or StoryRepository()
    segments_by_id = {s["segment_id"]: s for s in segments}
    rev = graph_revision(graph)
    cache = load_continuity_cache(story_id)
    cache_edges: dict[str, dict[str, Any]] = dict(cache.get("edges") or {})
    cache_changed = False

    llm_targets: list[EdgeContinuityInput] = []
    llm_keys: set[str] = set()

    for seg in segments:
        if not force and seg.get("video_status") == "ready":
            _apply_continuity_to_segment(
                seg,
                continues=bool(seg.get("continues_from_prev_shot")),
                reason=str(seg.get("continuity_reason") or "READY"),
            )
            continue

        blocked, reason_code = apply_hard_rules(seg, graph, segments_by_id)
        if blocked:
            _apply_continuity_to_segment(seg, continues=False, reason=reason_code or "BLOCKED")
            continue

        key = _edge_key(seg["from_node_id"], seg["to_node_id"])
        if not force and cache.get("graph_revision") == rev and key in cache_edges:
            cached = cache_edges[key]
            _apply_continuity_to_segment(
                seg,
                continues=bool(cached.get("continues")),
                reason=f"CACHE:{cached.get('reason', '')}",
            )
            continue

        if key not in llm_keys:
            llm_keys.add(key)
            from_node = graph.nodes.get(seg["from_node_id"])
            to_node = graph.nodes.get(seg["to_node_id"])
            llm_targets.append(
                EdgeContinuityInput(
                    segment_id=seg["segment_id"],
                    from_node_id=seg["from_node_id"],
                    to_node_id=seg["to_node_id"],
                    pred_segment_id=seg.get("pred_segment_id"),
                    option_label=_option_label(graph, seg),
                    from_title=from_node.title if from_node else "",
                    from_summary=(from_node.summary or "")[:200] if from_node else "",
                    to_title=to_node.title if to_node else "",
                    to_summary=(to_node.summary or "")[:200] if to_node else "",
                )
            )

    if llm_targets:
        settings = get_settings()
        meta = repo.load_meta(story_id)
        inspiration = meta.inspiration or ""
        geekai = GeekAIClient()
        try:
            for batch_start in range(0, len(llm_targets), _BATCH_SIZE):
                batch = llm_targets[batch_start : batch_start + _BATCH_SIZE]
                user = build_shot_continuity_user(inspiration, batch)
                try:
                    data = await geekai.chat(
                        [
                            {"role": "system", "content": SHOT_CONTINUITY_SYSTEM},
                            {"role": "user", "content": user},
                        ],
                        model=settings.prompt_model,
                        tools=None,
                        tool_choice=None,
                    )
                    raw = (data["choices"][0]["message"]["content"] or "").strip()
                    parsed = parse_shot_continuity_response(raw)
                except QuotaExhaustedError as exc:
                    repo.append_event(
                        story_id,
                        phase=FissionPhase.done,
                        type="shot_continuity",
                        message="镜头承接标注额度耗尽，本批边降级为 synthetic",
                        payload={"error": str(exc)},
                    )
                    parsed = {}
                    for edge in batch:
                        parsed[(edge.from_node_id, edge.to_node_id)] = (False, "QUOTA")
                except Exception:
                    parsed = {}

                for edge in batch:
                    key = _edge_key(edge.from_node_id, edge.to_node_id)
                    continues, llm_reason = lookup_llm_edge_result(parsed, edge)
                    reason = f"LLM:{llm_reason}" if llm_reason != "LLM_OMIT" else "LLM_OMIT"
                    cache_edges[key] = {"continues": continues, "reason": llm_reason}
                    cache_changed = True
                    for seg in segments:
                        if (
                            seg["from_node_id"] == edge.from_node_id
                            and seg["to_node_id"] == edge.to_node_id
                            and (force or seg.get("video_status") != "ready")
                        ):
                            blocked, code = apply_hard_rules(seg, graph, segments_by_id)
                            if blocked:
                                _apply_continuity_to_segment(seg, continues=False, reason=code or "BLOCKED")
                            else:
                                _apply_continuity_to_segment(seg, continues=continues, reason=reason)
        finally:
            await geekai.aclose()

    for seg in segments:
        if force or "first_frame_source" not in seg or seg.get("video_status") != "ready":
            seg["first_frame_source"] = derive_first_frame_source(seg)

    if cache_changed or cache.get("graph_revision") != rev:
        save_continuity_cache(
            story_id,
            {"version": 1, "graph_revision": rev, "edges": cache_edges},
        )

    return segments
