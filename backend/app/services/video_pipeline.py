from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import select

from backend.app.ai.dashscope_omni import DashScopeOmniClient
from backend.app.ai.ephone_video import EphoneVideoClient
from backend.app.ai.errors import QuotaExhaustedError
from backend.app.ai.geekai_image import GeekAIImageClient
from backend.app.config import get_settings
from backend.app.infrastructure.db import get_session_factory
from backend.app.infrastructure.orm import StorySegmentRow
from backend.app.infrastructure.paths import (
    segment_last_frame_path,
    segment_video_path,
    shot_prompt_path,
    story_dir,
)
from backend.app.media.ffmpeg_frames import extract_last_frame_async
from backend.app.models.enums import FissionPhase, ProduceStatus
from backend.app.services.asset_pipeline import gather_with_quota_limit
from backend.app.services.first_frame import bind_prev_last_frame, synthesize_first_frame
from backend.app.services.produce_state import (
    enter_awaiting_video,
    load_blueprint,
    pause_produce,
    save_blueprint,
    set_produce_status,
)
from backend.app.services.segment_plan import (
    prefetch_frame_stats,
    prefetch_segments,
    prefetch_synthetic_segments,
    topo_waves,
)
from backend.app.services.story_repository import StoryRepository
from backend.app.services.video_duration import resolve_segment_duration, sync_segment_durations


def _segments_from_blueprint(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    return list(blueprint.get("segments") or [])


def _segments_by_id(segments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {s["segment_id"]: s for s in segments}


async def _persist_segment(story_id: str, segment: dict[str, Any]) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(StorySegmentRow).where(
                StorySegmentRow.story_id == story_id,
                StorySegmentRow.segment_id == segment["segment_id"],
            )
        )
        row = result.scalars().first()
        if row is None:
            return
        row.first_frame_path = segment.get("first_frame_path")
        row.last_frame_path = segment.get("last_frame_path")
        row.video_path = segment.get("video_path")
        row.video_status = segment.get("video_status", row.video_status)
        row.qc_status = segment.get("qc_status", row.qc_status)
        row.regen_count = int(segment.get("regen_count") or 0)
        row.ephone_task_id = segment.get("ephone_task_id")
        row.qc_reasons_json = json.dumps(segment.get("qc_reasons") or [], ensure_ascii=False)
        await session.commit()


async def batch_first_frames(
    story_id: str,
    wave: list[dict[str, Any]],
    blueprint: dict[str, Any],
    segments_by_id: dict[str, dict[str, Any]],
    *,
    repo: StoryRepository | None = None,
    wave_index: int = 0,
    modes: frozenset[str] | None = None,
) -> dict[str, int]:
    """生成首帧。modes 控制只合成(synthetic)或只承接尾帧(prev_last_frame)，默认两者都做。"""
    repo = repo or StoryRepository()
    settings = get_settings()
    lock = asyncio.Lock()
    synthetic_done = 0
    prev_done = 0
    active_modes = modes or frozenset({"synthetic", "prev_last_frame"})
    graph = repo.load_graph(story_id)

    if "synthetic" in active_modes and "prev_last_frame" in active_modes:
        stage_label = "首帧"
    elif "synthetic" in active_modes:
        stage_label = "合成首帧"
    else:
        stage_label = "承接尾帧"

    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=f"开始{stage_label}：第 {wave_index + 1} 波 {len(wave)} 段",
        payload={"wave": wave_index + 1, "count": len(wave), "stage": "frames_start", "modes": sorted(active_modes)},
    )

    image_client = GeekAIImageClient()
    try:
        if "synthetic" in active_modes:

            async def synth_one(seg: dict[str, Any]) -> None:
                nonlocal synthetic_done
                if seg.get("first_frame_path"):
                    return
                if seg.get("first_frame_source") != "synthetic":
                    return
                await synthesize_first_frame(
                    story_id, seg, blueprint, image_client=image_client, graph=graph
                )
                async with lock:
                    save_blueprint(story_id, blueprint)
                    await _persist_segment(story_id, seg)
                    synthetic_done += 1

            synthetic = [
                s
                for s in wave
                if s.get("first_frame_source") == "synthetic" and not s.get("first_frame_path")
            ]
            if synthetic:
                await gather_with_quota_limit(
                    [synth_one(s) for s in synthetic],
                    max_concurrency=settings.image_max_concurrency,
                )

        if "prev_last_frame" in active_modes:
            for seg in wave:
                if seg.get("first_frame_source") == "prev_last_frame" and not seg.get("first_frame_path"):
                    bind_prev_last_frame(story_id, seg, segments_by_id)
                    save_blueprint(story_id, blueprint)
                    await _persist_segment(story_id, seg)
                    prev_done += 1
    finally:
        await image_client.aclose()

    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=(
            f"{stage_label}完成：第 {wave_index + 1} 波"
            f"（合成 {synthetic_done}，承接尾帧 {prev_done}，共 {len(wave)} 段）"
        ),
        payload={
            "wave": wave_index + 1,
            "synthetic": synthetic_done,
            "prev_last_frame": prev_done,
            "total": len(wave),
            "stage": "frames_done",
            "modes": sorted(active_modes),
        },
    )
    return {"synthetic": synthetic_done, "prev_last_frame": prev_done}


def _load_shot_prompt_doc(story_id: str, node_id: str) -> dict[str, Any]:
    doc = json.loads(shot_prompt_path(story_id, node_id).read_text(encoding="utf-8"))
    if not doc.get("prompt_text"):
        raise RuntimeError(f"shot prompt 缺少 prompt_text: {node_id}")
    return doc


def _load_prompt_text(story_id: str, node_id: str) -> str:
    return _load_shot_prompt_doc(story_id, node_id).get("prompt_text") or ""


def _segment_duration(
    story_id: str,
    segment: dict[str, Any],
    *,
    repo: StoryRepository,
) -> int:
    node_id = segment["prompt_node_id"]
    shot = _load_shot_prompt_doc(story_id, node_id)
    graph = repo.load_graph(story_id)
    blueprint = load_blueprint(story_id)
    node_by_id = {n["node_id"]: n for n in blueprint.get("nodes", [])}
    g_node = graph.nodes.get(node_id)
    bp_node = node_by_id.get(node_id, {})
    duration = resolve_segment_duration(
        segment,
        shot,
        title=bp_node.get("title") or (g_node.title if g_node else ""),
        summary=bp_node.get("summary") or (g_node.summary if g_node else ""),
        node_kind=g_node.kind.value if g_node else bp_node.get("kind"),
    )
    segment["video_duration"] = duration
    return duration


async def generate_segment_video(
    story_id: str,
    segment: dict[str, Any],
    *,
    video_client: EphoneVideoClient | None = None,
    repo: StoryRepository | None = None,
) -> str:
    if segment.get("video_status") == "ready" and segment.get("video_path"):
        return segment["video_path"]

    repo = repo or StoryRepository()
    settings = get_settings()
    first_rel = segment.get("first_frame_path")
    if not first_rel:
        raise RuntimeError(f"segment {segment['segment_id']} 缺少首帧")
    first_frame = story_dir(story_id) / first_rel
    dest = segment_video_path(story_id, segment["segment_id"])
    node_id = segment["prompt_node_id"]
    shot = _load_shot_prompt_doc(story_id, node_id)
    prompt = shot["prompt_text"]
    duration = _segment_duration(story_id, segment, repo=repo)

    own_client = video_client is None
    client = video_client or EphoneVideoClient()
    try:
        task_id = await client.submit(
            model=settings.video_model,
            prompt=prompt,
            first_frame=first_frame,
            duration=duration,
        )
        segment["ephone_task_id"] = task_id
        urls = await client.wait_for_outputs(
            task_id,
            poll_interval=settings.video_poll_interval,
        )
        await client.download_video(urls[0], dest)
    finally:
        if own_client:
            await client.aclose()

    rel = f"assets/videos/{segment['segment_id']}.mp4"
    segment["video_path"] = rel
    segment["video_status"] = "ready"
    last_dest = segment_last_frame_path(story_id, segment["segment_id"])
    await extract_last_frame_async(dest, last_dest)
    segment["last_frame_path"] = f"assets/frames/{segment['segment_id']}_last.png"
    await _persist_segment(story_id, segment)
    return rel


async def run_first_frames_phase(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """仅为 synthetic 段合成首帧；承接尾帧段留到出片阶段按波次绑定。"""
    repo = repo or StoryRepository()
    blueprint = load_blueprint(story_id)
    graph = repo.load_graph(story_id)
    sync_segment_durations(story_id, blueprint, graph)
    save_blueprint(story_id, blueprint)
    segments = _segments_from_blueprint(blueprint)
    if not segments:
        raise RuntimeError("无 segment 计划，须先完成静态素材阶段")

    prefetch = prefetch_segments(segments)
    synthetic_pending = [
        s
        for s in prefetch_synthetic_segments(segments)
        if not s.get("first_frame_path")
    ]
    frame_stats = prefetch_frame_stats(segments)
    if not synthetic_pending:
        set_produce_status(repo, story_id, blueprint, ProduceStatus.frames)
        from backend.app.services.asset_pipeline import assemble_shot_prompts_from_script

        await assemble_shot_prompts_from_script(story_id, repo=repo, job_id=job_id)
        return {
            "ok": True,
            "generated": 0,
            "prefetch_total": len(prefetch),
            **frame_stats,
        }

    set_produce_status(repo, story_id, blueprint, ProduceStatus.frames)
    chain_total = frame_stats["chain_frames"]["total"]
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=(
            f"开始合成首帧：{len(synthetic_pending)} 段"
            f"（另有 {chain_total} 段承接尾帧，待出片时生成）"
        ),
        payload={
            "pending_synthetic": len(synthetic_pending),
            "chain_deferred": chain_total,
            "stage": "frames_start",
        },
    )
    segments_by_id = _segments_by_id(segments)

    try:
        await batch_first_frames(
            story_id,
            synthetic_pending,
            blueprint,
            segments_by_id,
            repo=repo,
            wave_index=0,
            modes=frozenset({"synthetic"}),
        )
        save_blueprint(story_id, blueprint)
    except QuotaExhaustedError as exc:
        save_blueprint(story_id, blueprint)
        if job_id:
            await pause_produce(
                repo,
                story_id=story_id,
                job_id=job_id,
                paused_from=ProduceStatus.frames,
                exc=exc,
                blueprint=blueprint,
                in_flight={
                    "kind": "synthetic_frames",
                    "segment_ids": [s["segment_id"] for s in synthetic_pending],
                },
            )
        raise

    frame_stats = prefetch_frame_stats(segments)
    set_produce_status(repo, story_id, blueprint, ProduceStatus.frames)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=(
            f"合成首帧完成：{frame_stats['synthetic_frames']['ready']}/"
            f"{frame_stats['synthetic_frames']['total']}"
            f"（承接尾帧 {frame_stats['chain_frames']['total']} 段待出片）"
        ),
        payload={**frame_stats, "stage": "frames_done"},
    )

    from backend.app.services.asset_pipeline import assemble_shot_prompts_from_script

    await assemble_shot_prompts_from_script(story_id, repo=repo, job_id=job_id)

    return {
        "ok": True,
        "generated": len(synthetic_pending),
        "prefetch_total": len(prefetch),
        **frame_stats,
    }


async def run_video_generation(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    blueprint = load_blueprint(story_id)
    graph = repo.load_graph(story_id)
    sync_segment_durations(story_id, blueprint, graph)
    save_blueprint(story_id, blueprint)
    segments = _segments_from_blueprint(blueprint)
    if not segments:
        raise RuntimeError("无 segment 计划，须先完成静态素材阶段")

    prefetch = prefetch_segments(segments)
    pending = [s for s in prefetch if s.get("video_status") != "ready"]
    if not pending:
        set_produce_status(repo, story_id, blueprint, ProduceStatus.videos)
        return {"ok": True, "generated": 0, "prefetch_total": len(prefetch)}

    set_produce_status(repo, story_id, blueprint, ProduceStatus.videos)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=(
            f"开始预生产视频：{len(pending)} 段"
            f"（全库 {len(segments)}，按需 {len(segments) - len(prefetch)} 留运行时）"
        ),
        payload={"prefetch_pending": len(pending), "total": len(segments)},
    )
    segments_by_id = _segments_by_id(segments)
    waves = topo_waves(pending)
    settings = get_settings()
    generated: list[str] = []
    lock = asyncio.Lock()

    video_client = EphoneVideoClient()
    try:
        for wave_index, wave in enumerate(waves):
            try:
                await batch_first_frames(
                    story_id,
                    wave,
                    blueprint,
                    segments_by_id,
                    repo=repo,
                    wave_index=wave_index,
                    modes=frozenset({"prev_last_frame"}),
                )
                save_blueprint(story_id, blueprint)

                repo.append_event(
                    story_id,
                    phase=FissionPhase.done,
                    type="video",
                    message=f"开始出片：第 {wave_index + 1} 波 {len(wave)} 段",
                    payload={"wave": wave_index + 1, "count": len(wave), "stage": "videos_start"},
                )

                async def one(seg: dict[str, Any]) -> str:
                    sid = seg["segment_id"]
                    if seg.get("video_status") == "ready":
                        return sid
                    await generate_segment_video(
                        story_id, seg, video_client=video_client, repo=repo
                    )
                    async with lock:
                        save_blueprint(story_id, blueprint)
                    return sid

                pending_video = [s for s in wave if s.get("video_status") != "ready"]
                await gather_with_quota_limit(
                    [one(s) for s in pending_video],
                    max_concurrency=settings.video_max_concurrency,
                )
                generated.extend(s["segment_id"] for s in wave)
                save_blueprint(story_id, blueprint)
                repo.append_event(
                    story_id,
                    phase=FissionPhase.done,
                    type="video",
                    message=(
                        f"出片完成：第 {wave_index + 1} 波"
                        f"（本次 {len(pending_video)} 段，累计 {len(generated)} 段）"
                    ),
                    payload={
                        "wave": wave_index + 1,
                        "generated": len(pending_video),
                        "total": len(generated),
                        "stage": "videos_done",
                    },
                )
            except QuotaExhaustedError as exc:
                save_blueprint(story_id, blueprint)
                if job_id:
                    await pause_produce(
                        repo,
                        story_id=story_id,
                        job_id=job_id,
                        paused_from=ProduceStatus.videos,
                        exc=exc,
                        blueprint=blueprint,
                        in_flight={
                            "kind": "video_wave",
                            "segment_ids": [s["segment_id"] for s in wave],
                        },
                    )
                raise
    finally:
        await video_client.aclose()

    set_produce_status(repo, story_id, blueprint, ProduceStatus.videos)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=f"视频出片完成：{len(generated)} 段",
        payload={"segment_ids": generated},
    )
    return {"ok": True, "generated": len(generated)}


async def qc_and_maybe_regen(
    story_id: str,
    segment: dict[str, Any],
    *,
    repo: StoryRepository | None = None,
    video_client: EphoneVideoClient | None = None,
    omni_client: DashScopeOmniClient | None = None,
) -> dict[str, Any]:
    from backend.app.services.qc_context import build_segment_qc_context

    settings = get_settings()
    repo = repo or StoryRepository()
    if segment.get("qc_status") == "pass":
        return {"status": "pass", "reasons": []}

    video_rel = segment.get("video_path")
    if not video_rel:
        return {"status": "fail", "reasons": ["missing video"]}
    video_path = story_dir(story_id) / video_rel
    qc_context = build_segment_qc_context(story_id, segment, repo=repo)

    own_omni = omni_client is None
    omni = omni_client or DashScopeOmniClient()
    try:
        qc = await omni.review_video(
            video_path=video_path,
            context=qc_context,
        )
        segment["qc_reasons"] = qc.get("reasons") or []
        if qc.get("status") == "pass":
            segment["qc_status"] = "pass"
            await _persist_segment(story_id, segment)
            return qc

        regen_count = int(segment.get("regen_count") or 0)
        while regen_count < settings.video_regen_max and qc.get("status") == "fail":
            task_id = segment.get("ephone_task_id")
            if not task_id:
                break
            own_video = video_client is None
            vclient = video_client or EphoneVideoClient()
            try:
                dest = segment_video_path(story_id, segment["segment_id"])
                new_task = await vclient.submit(
                    model=settings.video_regen_model,
                    source_task_id=task_id,
                )
                segment["ephone_task_id"] = new_task
                urls = await vclient.wait_for_outputs(
                    new_task, poll_interval=settings.video_poll_interval
                )
                await vclient.download_video(urls[0], dest)
                regen_count += 1
                segment["regen_count"] = regen_count
                segment["video_status"] = "ready"
                last_dest = segment_last_frame_path(story_id, segment["segment_id"])
                await extract_last_frame_async(dest, last_dest)
                segment["last_frame_path"] = f"assets/frames/{segment['segment_id']}_last.png"
                await _persist_segment(story_id, segment)
                qc = await omni.review_video(
                    video_path=dest,
                    context=qc_context,
                )
                segment["qc_reasons"] = qc.get("reasons") or []
            finally:
                if own_video:
                    await vclient.aclose()

        if qc.get("status") == "pass":
            segment["qc_status"] = "pass"
        else:
            segment["qc_status"] = "fail"
        await _persist_segment(story_id, segment)
        return qc
    finally:
        if own_omni:
            await omni.aclose()


async def run_qc_loop(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    blueprint = load_blueprint(story_id)
    segments = _segments_from_blueprint(blueprint)
    set_produce_status(repo, story_id, blueprint, ProduceStatus.qc)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="qc",
        message=f"开始质检：{len(segments)} 段",
        payload={"total": len(segments)},
    )

    passed = 0
    failed = 0

    omni = DashScopeOmniClient()
    try:
        for seg in prefetch_segments(segments):
            if seg.get("video_status") != "ready":
                continue
            if seg.get("qc_status") == "pass":
                passed += 1
                continue
            try:
                qc = await qc_and_maybe_regen(
                    story_id,
                    seg,
                    repo=repo,
                    omni_client=omni,
                )
            except QuotaExhaustedError as exc:
                save_blueprint(story_id, blueprint)
                if job_id:
                    await pause_produce(
                        repo,
                        story_id=story_id,
                        job_id=job_id,
                        paused_from=ProduceStatus.qc,
                        exc=exc,
                        blueprint=blueprint,
                        in_flight={"kind": "qc", "segment_id": seg["segment_id"]},
                    )
                raise
            if qc.get("status") == "pass":
                passed += 1
                repo.append_event(
                    story_id,
                    phase=FissionPhase.done,
                    type="qc",
                    message=f"质检通过：{seg['segment_id']}",
                    payload={"segment_id": seg["segment_id"]},
                )
            else:
                failed += 1
                repo.append_event(
                    story_id,
                    phase=FissionPhase.done,
                    type="qc",
                    message=f"质检未通过：{seg['segment_id']}",
                    payload={"segment_id": seg["segment_id"], "reasons": qc.get("reasons")},
                )
            save_blueprint(story_id, blueprint)
    finally:
        await omni.aclose()

    if failed == 0 and passed > 0:
        set_produce_status(repo, story_id, blueprint, ProduceStatus.ready)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="qc",
        message=f"质检完成：pass={passed} fail={failed}",
        payload={"pass": passed, "fail": failed},
    )
    return {"ok": True, "pass": passed, "fail": failed}
