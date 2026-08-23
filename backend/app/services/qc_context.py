from __future__ import annotations

from typing import Any

from backend.app.services.produce_state import load_blueprint
from backend.app.services.story_repository import StoryRepository
from backend.app.services.video_pipeline import _load_prompt_text


def build_segment_qc_context(
    story_id: str,
    segment: dict[str, Any],
    *,
    repo: StoryRepository,
) -> str:
    graph = repo.load_graph(story_id)
    blueprint = load_blueprint(story_id)
    node_id = segment["prompt_node_id"]
    node = graph.nodes.get(node_id)
    title = node.title if node else ""
    summary = node.summary if node else ""

    prompt_text = _load_prompt_text(story_id, node_id)

    char_by_id = {c["character_id"]: c for c in blueprint.get("characters") or []}
    scene_by_id = {s["scene_id"]: s for s in blueprint.get("scenes") or []}
    bp_node = next((n for n in blueprint.get("nodes") or [] if n.get("node_id") == node_id), {})
    char_ids = bp_node.get("character_ids") or (list(node.character_ids) if node else [])
    scene_id = bp_node.get("scene_id") or (node.scene_id if node else None)
    scene = scene_by_id.get(scene_id or "", {})

    char_lines = "\n".join(
        f"- {char_by_id[cid]['name']}: {char_by_id[cid].get('appearance_prompt', '')}"
        for cid in char_ids
        if cid in char_by_id
    ) or "- （无）"

    blocks = [
        f"【本镜节点】{title}",
        f"【剧情结果】{summary}",
        f"【分镜剧本】\n{prompt_text}",
        f"【人物】\n{char_lines}",
        f"【场景】{scene.get('name', '')}：{scene.get('visual_prompt', '')}",
        "【审查范围】仅判断上述单段视频内部是否合理。",
    ]
    return "\n".join(blocks)
