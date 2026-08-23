from __future__ import annotations

import math
from typing import Any

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import PlotLine, StoryGraph

PRODUCE_TIER_PREFETCH = "prefetch"
PRODUCE_TIER_ON_DEMAND = "on_demand"

_OUTCOME_SCORE = {"completed": 4, "near": 3, "deferred": 2, "failed": 1}


def segment_id(from_node_id: str, to_node_id: str) -> str:
    return f"seg_{from_node_id}_{to_node_id}"


def derive_first_frame_source(segment: dict[str, Any]) -> str:
    if segment.get("from_is_root"):
        return "synthetic"
    preds = segment.get("pred_candidate_ids") or []
    if len(preds) > 1 or not segment.get("pred_segment_id"):
        return "synthetic"
    if segment.get("continues_from_prev_shot"):
        return "prev_last_frame"
    return "synthetic"


def _option_for_edge(graph: StoryGraph, from_id: str, to_id: str) -> str | None:
    for opt in graph.options:
        if opt.from_node_id == from_id and opt.to_node_id == to_id:
            return opt.id
    for edge in graph.edges:
        if edge.source == from_id and edge.target == to_id:
            return edge.option_id
    return None


def expand_segments(
    graph: StoryGraph,
    plot_lines: list[PlotLine],
) -> list[dict[str, Any]]:
    """从合格剧情线展开边级 segment；全局去重。"""
    by_id: dict[str, dict[str, Any]] = {}
    pred_map: dict[str, set[str]] = {}

    for pl in plot_lines:
        path = pl.node_path
        for i in range(len(path) - 1):
            from_id, to_id = path[i], path[i + 1]
            sid = segment_id(from_id, to_id)
            if i > 0:
                pred_sid = segment_id(path[i - 1], from_id)
                pred_map.setdefault(sid, set()).add(pred_sid)

            if sid in by_id:
                lines = by_id[sid].setdefault("source_line_ids", [])
                if pl.line_id not in lines:
                    lines.append(pl.line_id)
                continue

            to_node = graph.nodes[to_id]
            scene_id_val = to_node.scene_id
            prompt_node_id = to_id
            if to_node.script is None and from_id != graph.root_id:
                prompt_node_id = from_id
            pred_candidates: list[str] = []
            pred_segment: str | None = None
            if i > 0:
                pred_segment = segment_id(path[i - 1], from_id)
                pred_candidates = [pred_segment]

            by_id[sid] = {
                "segment_id": sid,
                "from_node_id": from_id,
                "to_node_id": to_id,
                "from_is_root": from_id == graph.root_id,
                "option_id": _option_for_edge(graph, from_id, to_id),
                "scene_id": scene_id_val,
                "pred_segment_id": pred_segment,
                "pred_candidate_ids": pred_candidates,
                "continues_from_prev_shot": False,
                "continuity_reason": None,
                "first_frame_source": "synthetic",
                "first_frame_path": None,
                "last_frame_path": None,
                "video_path": None,
                "prompt_node_id": to_id,
                "shot_prompt_status": "pending",
                "video_status": "pending",
                "qc_status": "pending",
                "regen_count": 0,
                "qc_reasons": [],
                "source_line_ids": [pl.line_id],
                "produce_tier": PRODUCE_TIER_PREFETCH,
                "video_duration": None,
            }

    for sid, seg in by_id.items():
        preds = sorted(pred_map.get(sid, set()))
        seg["pred_candidate_ids"] = preds
        if len(preds) > 1:
            seg["pred_segment_id"] = None
        elif len(preds) == 1:
            seg["pred_segment_id"] = preds[0]
        else:
            seg["pred_segment_id"] = None
        seg["first_frame_source"] = derive_first_frame_source(seg)

    return list(by_id.values())


def _line_priority(graph: StoryGraph, pl: PlotLine) -> tuple[int, int, int]:
    main_kinds = (NodeKind.root, NodeKind.main)
    main_hits = sum(
        1
        for nid in pl.node_path
        if nid in graph.nodes and graph.nodes[nid].kind in main_kinds
    )
    outcome = _OUTCOME_SCORE.get(pl.outcome or "", 2)
    return (main_hits, outcome, -len(pl.node_path))


def annotate_prefetch_tiers(
    graph: StoryGraph,
    plot_lines: list[PlotLine],
    segments: list[dict[str, Any]],
    *,
    ratio: float = 0.8,
) -> list[dict[str, Any]]:
    """标记预生产片段（主线 + 易达剧情线，约 ratio）与运行时按需片段。"""
    if not segments:
        return segments

    target = max(1, math.ceil(len(segments) * ratio))
    if ratio >= 1.0:
        target = len(segments)

    prefetch_ids: set[str] = set()
    if plot_lines:
        main_pl = max(plot_lines, key=lambda pl: _line_priority(graph, pl))
        for i in range(len(main_pl.node_path) - 1):
            prefetch_ids.add(segment_id(main_pl.node_path[i], main_pl.node_path[i + 1]))

    for pl in sorted(plot_lines, key=lambda pl: _line_priority(graph, pl), reverse=True):
        if len(prefetch_ids) >= target:
            break
        for i in range(len(pl.node_path) - 1):
            prefetch_ids.add(segment_id(pl.node_path[i], pl.node_path[i + 1]))
            if len(prefetch_ids) >= target:
                break

    for seg in segments:
        sid = seg["segment_id"]
        if sid in prefetch_ids:
            seg["produce_tier"] = PRODUCE_TIER_PREFETCH
            if seg.get("video_status") == "deferred":
                seg["video_status"] = "pending"
        else:
            seg["produce_tier"] = PRODUCE_TIER_ON_DEMAND
            if seg.get("video_status") != "ready":
                seg["video_status"] = "deferred"

    return segments


def prefetch_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in segments if s.get("produce_tier", PRODUCE_TIER_PREFETCH) == PRODUCE_TIER_PREFETCH]


def prefetch_synthetic_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        s
        for s in prefetch_segments(segments)
        if s.get("first_frame_source") == "synthetic"
    ]


def prefetch_chain_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        s
        for s in prefetch_segments(segments)
        if s.get("first_frame_source") == "prev_last_frame"
    ]


def prefetch_frame_stats(segments: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    synthetic = prefetch_synthetic_segments(segments)
    chain = prefetch_chain_segments(segments)
    return {
        "synthetic_frames": {
            "total": len(synthetic),
            "ready": sum(1 for s in synthetic if s.get("first_frame_path")),
        },
        "chain_frames": {
            "total": len(chain),
            "ready": sum(1 for s in chain if s.get("first_frame_path")),
        },
    }


def topo_waves(segments: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按 pred_segment_id 依赖分波次；synthetic 无前驱的在波次 0。"""
    by_id = {s["segment_id"]: s for s in segments}
    deps: dict[str, set[str]] = {}
    for seg in segments:
        sid = seg["segment_id"]
        if (
            seg.get("first_frame_source") == "prev_last_frame"
            and seg.get("pred_segment_id")
            and seg["pred_segment_id"] in by_id
        ):
            deps[sid] = {seg["pred_segment_id"]}
        else:
            deps[sid] = set()

    done: set[str] = set()
    waves: list[list[dict[str, Any]]] = []
    pending = list(segments)
    while len(done) < len(segments):
        wave = [s for s in pending if s["segment_id"] not in done and deps[s["segment_id"]].issubset(done)]
        if not wave:
            raise RuntimeError("segment dependency cycle detected")
        waves.append(wave)
        done.update(s["segment_id"] for s in wave)
    return waves
