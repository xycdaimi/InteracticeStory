from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, TypeVar

from sqlalchemy import select

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.ai.geekai_image import GeekAIImageClient
from backend.app.config import get_settings
from backend.app.infrastructure.db import get_session_factory
from backend.app.infrastructure.orm import CharacterRow, SceneRow
from backend.app.infrastructure.paths import character_image_path, ensure_asset_dirs, scene_image_path, shot_prompt_path
from backend.app.models.enums import FissionPhase, ProduceStatus
from backend.app.services.produce_state import (
    load_blueprint,
    pause_produce,
    save_blueprint,
    set_produce_status,
)
from backend.app.services.story_repository import StoryRepository

T = TypeVar("T")


async def gather_with_quota_limit(
    coros: list[Awaitable[T]],
    *,
    max_concurrency: int,
) -> list[T]:
    sem = asyncio.Semaphore(max_concurrency)

    async def run(coro: Awaitable[T]) -> T:
        async with sem:
            return await coro

    results = await asyncio.gather(*[run(c) for c in coros], return_exceptions=True)
    quota: QuotaExhaustedError | None = None
    out: list[T] = []
    for item in results:
        if isinstance(item, QuotaExhaustedError):
            quota = item
            continue
        if isinstance(item, BaseException):
            raise item
        out.append(item)
    if quota is not None:
        raise quota
    return out


async def _update_character_ready(
    story_id: str, character_id: str, image_path: str
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(CharacterRow).where(
                CharacterRow.story_id == story_id,
                CharacterRow.character_id == character_id,
            )
        )
        row = result.scalars().first()
        if row is not None:
            row.image_path = image_path
            row.status = "ready"
            await session.commit()


async def _update_scene_ready(story_id: str, scene_id: str, image_path: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(SceneRow).where(
                SceneRow.story_id == story_id,
                SceneRow.scene_id == scene_id,
            )
        )
        row = result.scalars().first()
        if row is not None:
            row.image_path = image_path
            row.status = "ready"
            await session.commit()


async def _apply_shot_prompt_file(
    story_id: str,
    nid: str,
    *,
    blueprint: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
) -> bool:
    """若磁盘已有提示词文件，写回 blueprint 与 DB，避免热重载后重复生成。"""
    from backend.app.infrastructure.orm import ShotPromptRow
    from sqlalchemy import delete

    path = shot_prompt_path(story_id, nid)
    if not path.exists():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not doc.get("prompt_text"):
        return False

    char_ids = doc.get("character_ids") or []
    scene_id = doc.get("scene_id")
    ref_paths = doc.get("ref_image_paths") or []
    prompt_text = doc["prompt_text"]

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            delete(ShotPromptRow).where(
                ShotPromptRow.story_id == story_id,
                ShotPromptRow.node_id == nid,
            )
        )
        session.add(
            ShotPromptRow(
                story_id=story_id,
                node_id=nid,
                prompt_text=prompt_text,
                character_ids_json=json.dumps(char_ids, ensure_ascii=False),
                scene_id=scene_id,
                ref_image_paths_json=json.dumps(ref_paths, ensure_ascii=False),
                status="ready",
            )
        )
        await session.commit()

    if nid in node_by_id:
        node_by_id[nid]["shot_prompt_status"] = "ready"
    return True


async def _reconcile_shot_prompts_from_disk(
    story_id: str,
    *,
    blueprint: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    plot_node_ids: set[str],
) -> int:
    restored = 0
    for nid in plot_node_ids:
        if node_by_id.get(nid, {}).get("shot_prompt_status") == "ready":
            continue
        if await _apply_shot_prompt_file(
            story_id, nid, blueprint=blueprint, node_by_id=node_by_id
        ):
            restored += 1
    if restored:
        save_blueprint(story_id, blueprint)
    return restored


async def generate_cast_images(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    settings = get_settings()
    blueprint = load_blueprint(story_id)
    ensure_asset_dirs(story_id)
    pending = [c for c in blueprint.get("characters", []) if c.get("status") != "ready"]
    if not pending:
        set_produce_status(repo, story_id, blueprint, ProduceStatus.cast)
        return {"ok": True, "generated": 0, "skipped": len(blueprint.get("characters", []))}

    image_client = GeekAIImageClient()
    try:

        async def one(char: dict[str, Any]) -> str:
            dest = character_image_path(story_id, char["character_id"])
            try:
                await image_client.generate_png(
                    model=settings.image_character_model,
                    prompt=char["appearance_prompt"],
                    dest=dest,
                    size=settings.image_character_size,
                )
            except QuotaExhaustedError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"人物「{char['name']}」({char['character_id']}) 出图失败: {exc}"
                ) from exc
            rel = f"assets/characters/{char['character_id']}.png"
            char["image_path"] = rel
            char["status"] = "ready"
            await _update_character_ready(story_id, char["character_id"], rel)
            save_blueprint(story_id, blueprint)
            return char["character_id"]

        try:
            generated = await gather_with_quota_limit(
                [one(c) for c in pending],
                max_concurrency=settings.image_max_concurrency,
            )
        except QuotaExhaustedError as exc:
            save_blueprint(story_id, blueprint)
            if job_id:
                await pause_produce(
                    repo,
                    story_id=story_id,
                    job_id=job_id,
                    paused_from=ProduceStatus.cast,
                    exc=exc,
                    blueprint=blueprint,
                )
            raise
    finally:
        await image_client.aclose()

    save_blueprint(story_id, blueprint)
    set_produce_status(repo, story_id, blueprint, ProduceStatus.cast)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="assets",
        message=f"人物素材完成：{len(generated)} 张",
        payload={"character_ids": generated},
    )
    return {"ok": True, "generated": len(generated)}


async def generate_scene_images(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    settings = get_settings()
    blueprint = load_blueprint(story_id)
    ensure_asset_dirs(story_id)
    pending = [s for s in blueprint.get("scenes", []) if s.get("status") != "ready"]
    if not pending:
        set_produce_status(repo, story_id, blueprint, ProduceStatus.scenes)
        return {"ok": True, "generated": 0}

    set_produce_status(repo, story_id, blueprint, ProduceStatus.scenes)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="assets",
        message=f"开始生成场景图：{len(pending)} 张",
        payload={"pending": len(pending)},
    )

    image_client = GeekAIImageClient()
    try:

        async def one(scene: dict[str, Any]) -> str:
            dest = scene_image_path(story_id, scene["scene_id"])
            try:
                await image_client.generate_png(
                    model=settings.image_scene_model,
                    prompt=scene["visual_prompt"],
                    dest=dest,
                    size=settings.image_scene_size,
                )
            except QuotaExhaustedError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"场景「{scene['name']}」({scene['scene_id']}) 出图失败: {exc}"
                ) from exc
            rel = f"assets/scenes/{scene['scene_id']}.png"
            scene["image_path"] = rel
            scene["status"] = "ready"
            await _update_scene_ready(story_id, scene["scene_id"], rel)
            save_blueprint(story_id, blueprint)
            return scene["scene_id"]

        try:
            generated = await gather_with_quota_limit(
                [one(s) for s in pending],
                max_concurrency=settings.image_max_concurrency,
            )
        except QuotaExhaustedError as exc:
            save_blueprint(story_id, blueprint)
            if job_id:
                await pause_produce(
                    repo,
                    story_id=story_id,
                    job_id=job_id,
                    paused_from=ProduceStatus.scenes,
                    exc=exc,
                    blueprint=blueprint,
                )
            raise
    finally:
        await image_client.aclose()

    save_blueprint(story_id, blueprint)
    set_produce_status(repo, story_id, blueprint, ProduceStatus.scenes)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="assets",
        message=f"场景素材完成：{len(generated)} 张",
        payload={"scene_ids": generated},
    )
    return {"ok": True, "generated": len(generated)}


def merge_segment_state(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """拓扑字段用 new；生产进度用 old 保留。"""
    if old is None:
        return new
    merged = {**new}
    for key in (
        "first_frame_path",
        "last_frame_path",
        "video_path",
        "shot_prompt_status",
        "video_status",
        "qc_status",
        "regen_count",
        "qc_reasons",
        "video_duration",
        "ephone_task_id",
    ):
        if old.get(key):
            merged[key] = old[key]
    if old.get("video_status") == "ready":
        if "continues_from_prev_shot" in old:
            merged["continues_from_prev_shot"] = old["continues_from_prev_shot"]
        if old.get("continuity_reason"):
            merged["continuity_reason"] = old["continuity_reason"]
        merged["first_frame_source"] = old.get("first_frame_source") or merged["first_frame_source"]
    return merged


async def _persist_segment_continuity(story_id: str, segments: list[dict[str, Any]]) -> None:
    from sqlalchemy import select

    from backend.app.infrastructure.orm import StorySegmentRow

    factory = get_session_factory()
    async with factory() as session:
        for seg in segments:
            result = await session.execute(
                select(StorySegmentRow).where(
                    StorySegmentRow.story_id == story_id,
                    StorySegmentRow.segment_id == seg["segment_id"],
                )
            )
            row = result.scalars().first()
            if row is None:
                continue
            row.continues_from_prev_shot = bool(seg.get("continues_from_prev_shot"))
            row.continuity_reason = seg.get("continuity_reason")
            row.first_frame_source = seg.get("first_frame_source") or "synthetic"
        await session.commit()


async def force_reannotate_shot_continuity(
    story_id: str,
    repo: StoryRepository | None = None,
) -> dict[str, Any]:
    """强制重跑镜头承接标注；保留已有首帧/视频等生产产物。"""
    from backend.app.services.persist import load_kept_lines
    from backend.app.services.segment_plan import expand_segments
    from backend.app.services.shot_continuity import annotate_shot_continuity, continuity_cache_path

    repo = repo or StoryRepository()
    graph = repo.load_graph(story_id)
    lines = load_kept_lines(story_id, graph)
    blueprint = load_blueprint(story_id)
    old_by_id = {s["segment_id"]: s for s in blueprint.get("segments") or []}
    fresh = expand_segments(graph, lines)
    segments = [merge_segment_state(old_by_id.get(s["segment_id"]), s) for s in fresh]
    cache_path = continuity_cache_path(story_id)
    if cache_path.is_file():
        cache_path.unlink()
    segments = await annotate_shot_continuity(
        story_id, graph, lines, segments, repo=repo, force=True
    )
    blueprint["segments"] = segments
    save_blueprint(story_id, blueprint)
    await _persist_segment_continuity(story_id, segments)
    chain = sum(1 for s in segments if s.get("first_frame_source") == "prev_last_frame")
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="shot_continuity",
        message=f"强制重标注完成：承接尾帧 {chain} / 共 {len(segments)} 段",
        payload={"prev_last_frame": chain, "total": len(segments)},
    )
    return {"ok": True, "total": len(segments), "prev_last_frame": chain}


async def sync_segments_to_blueprint(story_id: str, repo: StoryRepository | None = None) -> int:
    from backend.app.services.persist import load_kept_lines
    from backend.app.services.segment_plan import annotate_prefetch_tiers, expand_segments
    from backend.app.services.shot_continuity import annotate_shot_continuity

    repo = repo or StoryRepository()
    settings = get_settings()
    graph = repo.load_graph(story_id)
    lines = load_kept_lines(story_id, graph)
    blueprint = load_blueprint(story_id)
    old_by_id = {s["segment_id"]: s for s in blueprint.get("segments") or []}
    fresh = expand_segments(graph, lines)
    segments = [merge_segment_state(old_by_id.get(s["segment_id"]), s) for s in fresh]
    segments = await annotate_shot_continuity(story_id, graph, lines, segments, repo=repo)
    segments = annotate_prefetch_tiers(
        graph, lines, segments, ratio=settings.prefetch_segment_ratio
    )
    prefetch_count = sum(1 for s in segments if s.get("produce_tier") == "prefetch")
    on_demand_count = len(segments) - prefetch_count
    blueprint["segments"] = segments
    save_blueprint(story_id, blueprint)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="graph",
        message=f"片段计划：预生产 {prefetch_count} / 按需 {on_demand_count}（共 {len(segments)}）",
        payload={
            "prefetch": prefetch_count,
            "on_demand": on_demand_count,
            "total": len(segments),
        },
    )

    from sqlalchemy import delete

    from backend.app.infrastructure.orm import StorySegmentRow

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            delete(StorySegmentRow).where(StorySegmentRow.story_id == story_id)
        )
        for seg in segments:
            session.add(
                StorySegmentRow(
                    story_id=story_id,
                    segment_id=seg["segment_id"],
                    from_node_id=seg["from_node_id"],
                    to_node_id=seg["to_node_id"],
                    option_id=seg.get("option_id"),
                    scene_id=seg.get("scene_id"),
                    continues_from_prev_shot=bool(seg.get("continues_from_prev_shot")),
                    continuity_reason=seg.get("continuity_reason"),
                    first_frame_source=seg["first_frame_source"],
                    pred_segment_id=seg.get("pred_segment_id"),
                    first_frame_path=seg.get("first_frame_path"),
                    last_frame_path=seg.get("last_frame_path"),
                    video_path=seg.get("video_path"),
                    prompt_node_id=seg["prompt_node_id"],
                    shot_prompt_status=seg.get("shot_prompt_status", "pending"),
                    video_status=seg.get("video_status", "pending"),
                    qc_status=seg.get("qc_status", "pending"),
                    regen_count=int(seg.get("regen_count") or 0),
                    qc_reasons_json=json.dumps(seg.get("qc_reasons") or [], ensure_ascii=False),
                )
            )
        await session.commit()
    return len(segments)


async def assemble_shot_prompts_from_script(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """首帧与定妆就绪后，将【参考图】绑定段与时码剧本拼装为最终视频提示词。"""
    from backend.app.infrastructure.orm import ShotPromptRow
    from backend.app.services.video_duration import sync_segment_durations
    from backend.app.services.video_prompt_assemble import (
        assemble_prompt_from_script,
        resolve_ref_bindings,
    )
    from sqlalchemy import delete

    repo = repo or StoryRepository()
    settings = get_settings()
    blueprint = load_blueprint(story_id)
    graph = repo.load_graph(story_id)
    ensure_asset_dirs(story_id)

    if not blueprint.get("segments"):
        await sync_segments_to_blueprint(story_id, repo)
        blueprint = load_blueprint(story_id)

    char_by_id = {c["character_id"]: c for c in blueprint.get("characters", [])}
    node_by_id = {n["node_id"]: n for n in blueprint.get("nodes", [])}

    from backend.app.services.cast_extract import CharacterDraft
    from backend.app.services.character_registry import (
        build_character_slug_map,
        collect_script_character_tokens,
    )

    cast_drafts = [
        CharacterDraft(
            character_id=c["character_id"],
            name=c.get("name") or c["character_id"],
            appearance_prompt=c.get("appearance_prompt") or "",
            traits=c.get("traits") or [],
        )
        for c in blueprint.get("characters", [])
    ]
    slug_map = build_character_slug_map(
        collect_script_character_tokens(graph),
        cast_drafts,
        protagonist_id=blueprint.get("protagonist_character_id"),
    )

    plot_node_ids: set[str] = set()
    segments = blueprint.get("segments") or []
    for seg in segments:
        if seg.get("produce_tier", "prefetch") == "prefetch":
            plot_node_ids.add(seg["prompt_node_id"])

    await _reconcile_shot_prompts_from_disk(
        story_id,
        blueprint=blueprint,
        node_by_id=node_by_id,
        plot_node_ids=plot_node_ids,
    )

    pending_nodes = [
        nid
        for nid in plot_node_ids
        if node_by_id.get(nid, {}).get("shot_prompt_status") != "ready"
        and graph.nodes.get(nid) is not None
        and graph.nodes[nid].script is not None
    ]
    if not pending_nodes:
        sync_segment_durations(story_id, blueprint, graph)
        save_blueprint(story_id, blueprint)
        set_produce_status(repo, story_id, blueprint, ProduceStatus.prompts)
        return {"ok": True, "generated": 0}

    set_produce_status(repo, story_id, blueprint, ProduceStatus.prompts)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="assets",
        message=f"开始拼装视频提示词：{len(pending_nodes)} 条（参考图 + 时码剧本）",
        payload={"pending": len(pending_nodes)},
    )

    lock = asyncio.Lock()
    base_images = {
        cid: c["image_path"]
        for cid, c in char_by_id.items()
        if c.get("image_path")
    }
    char_images = dict(base_images)
    for token, canonical in slug_map.items():
        if canonical in base_images:
            char_images[token] = base_images[canonical]
    char_names = {cid: c.get("name") or cid for cid, c in char_by_id.items()}
    for token, canonical in slug_map.items():
        if canonical in char_names:
            char_names[token] = char_names[canonical]

    async def one(nid: str) -> str:
        if await _apply_shot_prompt_file(
            story_id, nid, blueprint=blueprint, node_by_id=node_by_id
        ):
            async with lock:
                save_blueprint(story_id, blueprint)
            return nid

        g_node = graph.nodes.get(nid)
        if g_node is None or g_node.script is None:
            raise RuntimeError(f"节点 {nid} 无 script，拒绝出片提示词")
        script = g_node.script

        continues_from_prev_shot = False
        first_frame_path = None
        for seg in segments:
            if seg.get("prompt_node_id") != nid:
                continue
            if seg.get("continues_from_prev_shot"):
                continues_from_prev_shot = True
            if seg.get("first_frame_path"):
                first_frame_path = seg["first_frame_path"]
                break

        bindings = resolve_ref_bindings(
            script,
            first_frame_path=first_frame_path,
            character_images=char_images,
            character_names=char_names,
            continues_from_prev_shot=continues_from_prev_shot,
        )
        prompt_text = assemble_prompt_from_script(
            script,
            bindings,
            continues_from_prev_shot=continues_from_prev_shot,
            pov_names=char_names,
        )
        duration_seconds = script.duration_seconds

        ref_paths = [b.path for b in bindings]
        ref_bindings = [
            {
                "path": b.path,
                "role": b.role,
                "depicts": b.depicts,
                "character_id": b.character_id,
            }
            for b in bindings
        ]
        char_ids = [b.character_id for b in bindings if b.character_id]

        prompt_doc = {
            "node_id": nid,
            "prompt_text": prompt_text,
            "duration_seconds": duration_seconds,
            "character_ids": char_ids,
            "scene_id": g_node.scene_id,
            "first_frame_path": first_frame_path,
            "ref_bindings": ref_bindings,
            "ref_image_paths": ref_paths,
            "status": "ready",
            "source": "script_assemble",
        }
        shot_prompt_path(story_id, nid).write_text(
            json.dumps(prompt_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                delete(ShotPromptRow).where(
                    ShotPromptRow.story_id == story_id,
                    ShotPromptRow.node_id == nid,
                )
            )
            session.add(
                ShotPromptRow(
                    story_id=story_id,
                    node_id=nid,
                    prompt_text=prompt_text,
                    character_ids_json=json.dumps(char_ids, ensure_ascii=False),
                    scene_id=g_node.scene_id,
                    ref_image_paths_json=json.dumps(ref_paths, ensure_ascii=False),
                    status="ready",
                )
            )
            await session.commit()

        async with lock:
            if nid in node_by_id:
                node_by_id[nid]["shot_prompt_status"] = "ready"
            for seg in segments:
                if seg.get("prompt_node_id") == nid:
                    seg["video_duration"] = duration_seconds
            save_blueprint(story_id, blueprint)
        return nid

    generated: list[str] = []
    try:
        generated = await gather_with_quota_limit(
            [one(nid) for nid in pending_nodes],
            max_concurrency=settings.prompt_max_concurrency,
        )
    except QuotaExhaustedError as exc:
        save_blueprint(story_id, blueprint)
        if job_id:
            await pause_produce(
                repo,
                story_id=story_id,
                job_id=job_id,
                paused_from=ProduceStatus.prompts,
                exc=exc,
                blueprint=blueprint,
            )
        raise

    save_blueprint(story_id, blueprint)
    sync_segment_durations(story_id, blueprint, graph)
    save_blueprint(story_id, blueprint)
    set_produce_status(repo, story_id, blueprint, ProduceStatus.prompts)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="assets",
        message=f"视频提示词拼装完成：{len(generated)} 条",
        payload={"node_ids": generated},
    )
    return {"ok": True, "generated": len(generated)}


# 兼容旧调用名
generate_shot_prompts = assemble_shot_prompts_from_script



async def run_static_assets(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    meta = repo.load_meta(story_id)
    if meta.produce_status == ProduceStatus.paused and meta.produce_paused_from:
        meta.produce_status = ProduceStatus(meta.produce_paused_from)
        meta.produce_paused_from = None
        meta.produce_pause_reason = None
        repo.save_meta(meta)

    results: dict[str, Any] = {}
    st = repo.load_meta(story_id).produce_status

    if st == ProduceStatus.none:
        results["cast"] = await generate_cast_images(story_id, repo=repo, job_id=job_id)
        if repo.load_meta(story_id).produce_status == ProduceStatus.paused:
            return results

    st = repo.load_meta(story_id).produce_status
    if st in (ProduceStatus.none, ProduceStatus.cast):
        results["scenes"] = await generate_scene_images(story_id, repo=repo, job_id=job_id)
        if repo.load_meta(story_id).produce_status == ProduceStatus.paused:
            return results

    results["segments"] = await sync_segments_to_blueprint(story_id, repo)
    await repo.sync_story_row(story_id)
    return results
