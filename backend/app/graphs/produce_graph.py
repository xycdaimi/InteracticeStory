from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from backend.app.models.enums import FissionPhase, ProduceStatus
from backend.app.services.asset_pipeline import (
    generate_cast_images,
    generate_scene_images,
    sync_segments_to_blueprint,
)
from backend.app.services.produce_state import load_blueprint, save_blueprint, set_produce_status
from backend.app.services.story_repository import StoryRepository


class ProduceGraphState(TypedDict, total=False):
    story_id: str
    job_id: str | None
    results: dict[str, Any]
    error: str | None


def _assert_characters_ready(story_id: str) -> None:
    bp = load_blueprint(story_id)
    pending = [
        c["character_id"]
        for c in bp.get("characters", [])
        if c.get("status") != "ready" or not c.get("image_path")
    ]
    if pending:
        raise RuntimeError(f"定妆图未齐，禁止进入首帧阶段：{pending}")


async def cast_images_node(state: ProduceGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    results = dict(state.get("results") or {})
    blueprint = load_blueprint(story_id)
    pending = [c for c in blueprint.get("characters", []) if c.get("status") != "ready"]
    if pending:
        repo.append_event(
            story_id,
            phase=FissionPhase.done,
            type="phase",
            message=f"生产 LangGraph：角色定妆图（{len(pending)}）…",
        )
        results["cast"] = await generate_cast_images(
            story_id, repo=repo, job_id=state.get("job_id")
        )
    _assert_characters_ready(story_id)
    return {"results": results}


async def scene_images_node(state: ProduceGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    results = dict(state.get("results") or {})
    blueprint = load_blueprint(story_id)
    pending = [s for s in blueprint.get("scenes", []) if s.get("status") != "ready"]
    if pending:
        repo.append_event(
            story_id,
            phase=FissionPhase.done,
            type="phase",
            message=f"生产 LangGraph：场景图（{len(pending)}）…",
        )
        results["scenes"] = await generate_scene_images(
            story_id, repo=repo, job_id=state.get("job_id")
        )
    return {"results": results}


async def sync_segments_node(state: ProduceGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    results = dict(state.get("results") or {})
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="log",
        message="生产 LangGraph：同步 segments…",
    )
    results["segments"] = await sync_segments_to_blueprint(story_id, repo)
    return {"results": results}


async def ready_for_frames_node(state: ProduceGraphState) -> dict[str, Any]:
    """定妆与场景就绪后进入首帧阶段；视频提示词在首帧合成后拼装。"""
    story_id = state["story_id"]
    repo = StoryRepository()
    _assert_characters_ready(story_id)
    blueprint = load_blueprint(story_id)
    set_produce_status(repo, story_id, blueprint, ProduceStatus.prompts)
    save_blueprint(story_id, blueprint)
    await repo.sync_story_row(story_id)
    return {"results": state.get("results") or {}}


def build_produce_static_graph():
    g = StateGraph(ProduceGraphState)
    g.add_node("cast", cast_images_node)
    g.add_node("scenes", scene_images_node)
    g.add_node("segments", sync_segments_node)
    g.add_node("ready_frames", ready_for_frames_node)
    g.add_edge(START, "cast")
    g.add_edge("cast", "scenes")
    g.add_edge("scenes", "segments")
    g.add_edge("segments", "ready_frames")
    g.add_edge("ready_frames", END)
    return g.compile()


async def run_produce_static_graph(
    story_id: str,
    *,
    repo: StoryRepository | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    repo = repo or StoryRepository()
    if not load_blueprint(story_id):
        raise RuntimeError("缺少 blueprint.json，须先 persist_graph")

    meta = repo.load_meta(story_id)
    if meta.produce_status == ProduceStatus.paused and meta.produce_paused_from:
        meta.produce_status = ProduceStatus(meta.produce_paused_from)
        meta.produce_paused_from = None
        meta.produce_pause_reason = None
        repo.save_meta(meta)

    graph = build_produce_static_graph()
    final = await graph.ainvoke(
        {"story_id": story_id, "job_id": job_id, "results": {}}
    )
    return final.get("results") or {}
