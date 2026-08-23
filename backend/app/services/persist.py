from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete

from backend.app.ai.geekai_client import GeekAIClient
from backend.app.infrastructure.db import get_session_factory
from backend.app.infrastructure.orm import (
    CharacterRow,
    SceneRow,
    StoryEdgeRow,
    StoryEndingRow,
    StoryNodeRow,
    StoryOptionRow,
    StoryPlotLineRow,
    StoryRow,
)
from backend.app.infrastructure.paths import blueprint_path, compliance_path
from backend.app.models.enums import (
    ComplianceStatus,
    FissionPhase,
    NodeKind,
    ProduceStatus,
)
from backend.app.models.story_graph import PlotLine, StoryGraph
from backend.app.services.cast_extract import extract_cast_and_bindings
from backend.app.services.character_registry import align_cast_with_scripts
from backend.app.services.story_repository import StoryRepository


def _atomic_write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_kept_lines(story_id: str, graph: StoryGraph) -> list[PlotLine]:
    path = compliance_path(story_id)
    if not path.exists():
        raise RuntimeError("缺少 compliance.json，须先 compliance_check")
    data = json.loads(path.read_text(encoding="utf-8"))
    kept_raw = data.get("kept_lines")
    if not kept_raw:
        kept_raw = [
            item
            for item in (data.get("lines") or [])
            if item.get("compliance_status") == ComplianceStatus.passed.value
        ]
    if not kept_raw:
        raise RuntimeError("没有合格剧情线，无法 persist")
    lines = [PlotLine.model_validate(item) for item in kept_raw]
    for pl in lines:
        for nid in pl.node_path:
            if nid not in graph.nodes:
                raise RuntimeError(f"合格线引用了已不存在的节点: {nid}")
    return lines


def build_blueprint(
    *,
    story_id: str,
    inspiration: str,
    graph: StoryGraph,
    lines: list[PlotLine],
    characters: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    protagonist_character_id: str | None = None,
) -> dict[str, Any]:
    endings = [
        {
            "ending_id": nid,
            "share_key": node.share_key,
            "outcome": node.outcome,
            "title": node.title,
        }
        for nid, node in graph.nodes.items()
        if node.kind == NodeKind.ending
    ]
    nodes = [
        {
            "node_id": nid,
            "kind": node.kind.value,
            "title": node.title,
            "summary": node.summary,
            "character_ids": list(node.character_ids),
            "scene_id": node.scene_id,
            "shot_prompt_status": "pending",
        }
        for nid, node in graph.nodes.items()
    ]
    return {
        "story_id": story_id,
        "inspiration": inspiration,
        "produce_status": ProduceStatus.none.value,
        "protagonist_character_id": protagonist_character_id,
        "characters": characters,
        "scenes": scenes,
        "endings": endings,
        "plot_lines": [pl.model_dump() for pl in lines],
        "nodes": nodes,
    }


async def persist_production_blueprint(
    story_id: str,
    repo: StoryRepository | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    meta = repo.load_meta(story_id)
    graph = repo.load_graph(story_id)
    if graph.open_plot_leaves():
        raise RuntimeError("仍有开放叶，须先 converge_endings + compliance_check")
    if meta.phase not in {FissionPhase.compliance, FissionPhase.persist}:
        if not compliance_path(story_id).exists():
            raise RuntimeError("须先完成 compliance_check")

    lines = load_kept_lines(story_id, graph)
    geekai = GeekAIClient()
    try:
        characters, scenes, bindings, protagonist_id = await extract_cast_and_bindings(
            meta.inspiration, graph, geekai
        )
    finally:
        await geekai.aclose()

    characters, _slug_map = align_cast_with_scripts(
        graph, characters, protagonist_id=protagonist_id
    )

    bind_map = {b.node_id: b for b in bindings}
    for nid, node in graph.nodes.items():
        if nid in bind_map:
            b = bind_map[nid]
            node.character_ids = list(b.character_ids)
            node.scene_id = b.scene_id

    char_docs = [
        {
            "character_id": c.character_id,
            "name": c.name,
            "appearance_prompt": c.appearance_prompt,
            "traits": c.traits,
            "image_path": None,
            "status": "pending",
        }
        for c in characters
    ]
    scene_docs = [
        {
            "scene_id": s.scene_id,
            "name": s.name,
            "visual_prompt": s.visual_prompt,
            "image_path": None,
            "status": "pending",
        }
        for s in scenes
    ]

    factory = get_session_factory()
    async with factory() as session:
        for model in (
            StoryNodeRow,
            StoryEdgeRow,
            StoryOptionRow,
            StoryPlotLineRow,
            StoryEndingRow,
            CharacterRow,
            SceneRow,
        ):
            await session.execute(delete(model).where(model.story_id == story_id))

        for nid, node in graph.nodes.items():
            session.add(
                StoryNodeRow(
                    story_id=story_id,
                    node_id=nid,
                    kind=node.kind.value,
                    title=node.title,
                    summary=node.summary,
                    parent_id=node.parent_id,
                    canvas_x=node.canvas_x,
                    canvas_y=node.canvas_y,
                    character_ids_json=json.dumps(node.character_ids, ensure_ascii=False),
                    scene_id=node.scene_id,
                    script_json=(
                        node.script.model_dump_json() if node.script is not None else None
                    ),
                )
            )
        for e in graph.edges:
            session.add(
                StoryEdgeRow(
                    story_id=story_id,
                    edge_id=e.id,
                    source=e.source,
                    target=e.target,
                    option_id=e.option_id,
                )
            )
        for o in graph.options:
            session.add(
                StoryOptionRow(
                    story_id=story_id,
                    option_id=o.id,
                    from_node_id=o.from_node_id,
                    to_node_id=o.to_node_id,
                    label=o.label,
                )
            )
        for pl in lines:
            session.add(
                StoryPlotLineRow(
                    story_id=story_id,
                    line_id=pl.line_id,
                    node_path_json=json.dumps(pl.node_path, ensure_ascii=False),
                    ending_id=pl.ending_id,
                    outcome=pl.outcome,
                    compliance_status=pl.compliance_status,
                    reasons_json=json.dumps(pl.reasons, ensure_ascii=False),
                )
            )
        for nid, node in graph.nodes.items():
            if node.kind != NodeKind.ending:
                continue
            session.add(
                StoryEndingRow(
                    story_id=story_id,
                    ending_id=nid,
                    share_key=node.share_key,
                    outcome=node.outcome,
                    title=node.title,
                )
            )
        for c in characters:
            session.add(
                CharacterRow(
                    story_id=story_id,
                    character_id=c.character_id,
                    name=c.name,
                    appearance_prompt=c.appearance_prompt,
                    traits_json=json.dumps(c.traits, ensure_ascii=False),
                    image_path=None,
                    status="pending",
                )
            )
        for s in scenes:
            session.add(
                SceneRow(
                    story_id=story_id,
                    scene_id=s.scene_id,
                    name=s.name,
                    visual_prompt=s.visual_prompt,
                    image_path=None,
                    status="pending",
                )
            )

        row = await session.get(StoryRow, story_id)
        if row is not None:
            row.phase = FissionPhase.persist.value
            row.line_count = graph.line_count
            row.ending_count = graph.ending_count()
            row.produce_status = ProduceStatus.none.value
        await session.commit()

    blueprint = build_blueprint(
        story_id=story_id,
        inspiration=meta.inspiration,
        graph=graph,
        lines=lines,
        characters=char_docs,
        scenes=scene_docs,
        protagonist_character_id=protagonist_id,
    )
    _atomic_write(
        blueprint_path(story_id),
        json.dumps(blueprint, ensure_ascii=False, indent=2),
    )

    meta.phase = FissionPhase.persist
    meta.produce_status = ProduceStatus.none
    meta.line_count = graph.line_count
    meta.ending_count = graph.ending_count()
    repo.save_graph(graph)
    repo.save_meta(meta)
    repo.append_event(
        story_id,
        phase=FissionPhase.persist,
        type="phase",
        message=(
            f"定稿入库：lines={len(lines)} characters={len(characters)} scenes={len(scenes)}"
        ),
        payload={
            "line_count": len(lines),
            "character_count": len(characters),
            "scene_count": len(scenes),
        },
    )
    return {
        "ok": True,
        "line_count": len(lines),
        "character_count": len(characters),
        "scene_count": len(scenes),
        "produce_status": ProduceStatus.none.value,
    }
