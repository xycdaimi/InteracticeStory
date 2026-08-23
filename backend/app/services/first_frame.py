from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from backend.app.ai.geekai_image import GeekAIImageClient
from backend.app.config import get_settings
from backend.app.infrastructure.paths import segment_first_frame_path, story_dir
from backend.app.models.story_graph import NodeScript, StoryGraph


def _resolve_asset(story_id: str, rel: str) -> Path:
    return story_dir(story_id) / rel


def _character_ids_for_frame(script: NodeScript) -> list[str]:
    ids = list(script.visual_plan.first_frame.covers_character_ids or [])
    for ref in script.visual_plan.character_refs:
        if ref.character_id not in ids:
            ids.append(ref.character_id)
    return ids


def _compose_first_frame_prompt_from_script(
    *,
    script: NodeScript,
    blueprint: dict[str, Any],
    scene_id: str | None,
) -> str:
    char_by_id = {c["character_id"]: c for c in blueprint.get("characters", [])}
    scene_by_id = {s["scene_id"]: s for s in blueprint.get("scenes", [])}
    scene = scene_by_id.get(scene_id or "", {})
    cast_bits = []
    for cid in _character_ids_for_frame(script):
        c = char_by_id.get(cid)
        if c:
            cast_bits.append(f"{c['name']}：{c['appearance_prompt']}")
    cast_text = "；".join(cast_bits) if cast_bits else "无特定人物"
    depicts = script.visual_plan.first_frame.depicts
    if not depicts and script.beats:
        depicts = script.beats[0].action
    return (
        f"电影剧照首帧，竖屏构图，{scene.get('name', '场景')}。"
        f"场景：{scene.get('visual_prompt', '')}。"
        f"人物：{cast_text}。"
        f"画面：{depicts}"
    )


async def synthesize_first_frame(
    story_id: str,
    segment: dict[str, Any],
    blueprint: dict[str, Any],
    *,
    image_client: GeekAIImageClient | None = None,
    graph: StoryGraph | None = None,
) -> Path:
    settings = get_settings()
    node_id = segment["prompt_node_id"]
    if graph is None:
        from backend.app.services.story_repository import StoryRepository

        graph = StoryRepository().load_graph(story_id)
    g_node = graph.nodes.get(node_id)
    if g_node is None or g_node.script is None:
        raise RuntimeError(f"节点 {node_id} 无 script，拒绝合成首帧")
    script = g_node.script
    prompt = _compose_first_frame_prompt_from_script(
        script=script,
        blueprint=blueprint,
        scene_id=g_node.scene_id,
    )
    dest = segment_first_frame_path(story_id, segment["segment_id"])
    own_client = image_client is None
    client = image_client or GeekAIImageClient()
    try:
        await client.generate_png(
            model=settings.image_scene_model,
            prompt=prompt,
            dest=dest,
            size=settings.image_scene_size,
        )
    finally:
        if own_client:
            await client.aclose()
    rel = f"assets/frames/{segment['segment_id']}_first.png"
    segment["first_frame_path"] = rel
    return dest


def bind_prev_last_frame(
    story_id: str,
    segment: dict[str, Any],
    segments_by_id: dict[str, dict[str, Any]],
) -> Path:
    pred_id = segment.get("pred_segment_id")
    if not pred_id:
        raise RuntimeError(f"segment {segment['segment_id']} 缺少 pred_segment_id")
    pred = segments_by_id.get(pred_id)
    if pred is None or not pred.get("last_frame_path"):
        raise RuntimeError(f"前驱 segment {pred_id} 尾帧未就绪")
    src = _resolve_asset(story_id, pred["last_frame_path"])
    if not src.exists():
        raise RuntimeError(f"前驱尾帧文件不存在: {src}")
    dest = segment_first_frame_path(story_id, segment["segment_id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    rel = f"assets/frames/{segment['segment_id']}_first.png"
    segment["first_frame_path"] = rel
    return dest
