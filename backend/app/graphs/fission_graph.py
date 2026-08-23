from __future__ import annotations

import json
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from backend.app.agents.fission_tools import FissionTools
from backend.app.graphs.branch_script_graph import run_branch_script_graph
from backend.app.graphs.consistency_graph import run_consistency_graph
from backend.app.graphs.plot_tree_graph import run_plot_tree_graph
from backend.app.graphs.produce_graph import run_produce_static_graph
from backend.app.graphs.story_bible_graph import run_story_bible_graph
from backend.app.infrastructure.paths import blueprint_path
from backend.app.models.enums import FissionPhase
from backend.app.services.story_repository import StoryRepository


class FissionGraphState(TypedDict, total=False):
    story_id: str
    stage: str
    fission_done: bool
    produce_done: bool
    done: bool
    error: str | None


async def collect_node(state: FissionGraphState) -> dict[str, Any]:
    """收集：确保配置/状态，写入灵感上下文，标记 collect 完成（无 ReAct）。"""
    story_id = state["story_id"]
    repo = StoryRepository()
    meta = repo.load_meta(story_id)
    if meta.phase not in (FissionPhase.idle, FissionPhase.collect):
        return {"stage": "bible"}

    meta.phase = FissionPhase.collect
    repo.save_meta(meta)
    repo.ensure_fission_config(story_id, inspiration=meta.inspiration)
    repo.ensure_story_state(story_id)
    if meta.inspiration.strip():
        repo.append_context(story_id, f"## Inspiration\n{meta.inspiration.strip()}")

    tools = FissionTools(story_id, repo=repo)
    result = tools.mark_collect_done()
    parsed = json.loads(result)
    if parsed.get("ok") is False:
        return {"error": parsed.get("error") or "mark_collect_done 失败", "stage": "failed"}
    return {"stage": "bible"}


async def bible_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    try:
        await run_story_bible_graph(story_id)
        return {"stage": "plot_tree"}
    except Exception as exc:
        return {"error": str(exc), "stage": "failed"}


async def plot_tree_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    try:
        await run_plot_tree_graph(story_id)
        return {"stage": "script"}
    except Exception as exc:
        return {"error": str(exc), "stage": "failed"}


async def script_node(state: FissionGraphState) -> dict[str, Any]:
    """写齐所有缺 script 的非 root 节点（含主线与分支）。"""
    story_id = state["story_id"]
    try:
        await run_branch_script_graph(story_id)
        return {"stage": "consistency"}
    except Exception as exc:
        return {"error": str(exc), "stage": "failed"}


async def consistency_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    try:
        await run_consistency_graph(story_id)
        return {"stage": "compliance"}
    except Exception as exc:
        return {"error": str(exc), "stage": "failed"}


async def compliance_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    tools = FissionTools(story_id, repo=repo)
    repo.append_event(
        story_id,
        phase=FissionPhase.compliance,
        type="phase",
        message="LangGraph：合规审查与剪枝",
    )
    result = await tools.compliance_check()
    parsed = json.loads(result)
    if parsed.get("error"):
        return {"error": str(parsed["error"]), "stage": "failed"}
    return {"stage": "persist"}


async def persist_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    tools = FissionTools(story_id, repo=repo)
    repo.append_event(
        story_id,
        phase=FissionPhase.persist,
        type="phase",
        message="LangGraph：定稿入库",
    )
    result = await tools.persist_graph()
    parsed = json.loads(result)
    if parsed.get("error"):
        return {"error": str(parsed["error"]), "stage": "failed"}
    return {"stage": "finish"}


async def finish_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    tools = FissionTools(story_id, repo=StoryRepository())
    result = tools.finish_fission()
    parsed = json.loads(result)
    if parsed.get("error"):
        return {"error": str(parsed["error"]), "stage": "failed"}
    meta = StoryRepository().load_meta(story_id)
    if meta.phase != FissionPhase.done:
        return {"error": "finish_fission 未将 phase 置为 done", "stage": "failed"}
    return {"fission_done": True, "stage": "produce"}


async def produce_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    if not blueprint_path(story_id).exists():
        return {
            "produce_done": False,
            "error": "缺少 blueprint，persist_graph 未成功",
            "stage": "failed",
        }
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="phase",
        message="开始素材与视频提示词（LangGraph 生产子图）",
    )
    await run_produce_static_graph(story_id, repo=repo)
    return {"produce_done": True, "stage": "done", "done": True}


async def fail_node(state: FissionGraphState) -> dict[str, Any]:
    story_id = state["story_id"]
    repo = StoryRepository()
    err = state.get("error") or "流程失败"
    repo.append_event(
        story_id,
        phase=FissionPhase.failed,
        type="error",
        message=err,
    )
    meta = repo.load_meta(story_id)
    if meta.phase != FissionPhase.done:
        meta.phase = FissionPhase.failed
        repo.save_meta(meta)
    return {"done": False, "error": err}


def _ok_or_fail(next_stage: str):
    def _route(state: FissionGraphState) -> Literal["fail"] | str:
        if state.get("error") or state.get("stage") == "failed":
            return "fail"
        return next_stage

    return _route


def _route_after_produce(state: FissionGraphState) -> Literal["__end__", "fail"]:
    if state.get("done"):
        return "__end__"
    return "fail"


def build_fission_graph():
    g = StateGraph(FissionGraphState)
    g.add_node("collect", collect_node)
    g.add_node("bible", bible_node)
    g.add_node("plot_tree", plot_tree_node)
    g.add_node("script", script_node)
    g.add_node("consistency", consistency_node)
    g.add_node("compliance", compliance_node)
    g.add_node("persist", persist_node)
    g.add_node("finish", finish_node)
    g.add_node("produce", produce_node)
    g.add_node("fail", fail_node)

    g.add_edge(START, "collect")
    g.add_conditional_edges(
        "collect", _ok_or_fail("bible"), {"bible": "bible", "fail": "fail"}
    )
    g.add_conditional_edges(
        "bible", _ok_or_fail("plot_tree"), {"plot_tree": "plot_tree", "fail": "fail"}
    )
    g.add_conditional_edges(
        "plot_tree", _ok_or_fail("script"), {"script": "script", "fail": "fail"}
    )
    g.add_conditional_edges(
        "script",
        _ok_or_fail("consistency"),
        {"consistency": "consistency", "fail": "fail"},
    )
    g.add_conditional_edges(
        "consistency",
        _ok_or_fail("compliance"),
        {"compliance": "compliance", "fail": "fail"},
    )
    g.add_conditional_edges(
        "compliance",
        lambda s: "persist" if s.get("stage") == "persist" else "fail",
        {"persist": "persist", "fail": "fail"},
    )
    g.add_conditional_edges(
        "persist",
        lambda s: "finish" if s.get("stage") == "finish" else "fail",
        {"finish": "finish", "fail": "fail"},
    )
    g.add_conditional_edges(
        "finish",
        lambda s: "produce" if s.get("stage") == "produce" else "fail",
        {"produce": "produce", "fail": "fail"},
    )
    g.add_conditional_edges(
        "produce", _route_after_produce, {"__end__": END, "fail": "fail"}
    )
    g.add_edge("fail", END)
    return g.compile()


def _build_fission_only_graph():
    g = StateGraph(FissionGraphState)
    g.add_node("collect", collect_node)
    g.add_node("bible", bible_node)
    g.add_node("plot_tree", plot_tree_node)
    g.add_node("script", script_node)
    g.add_node("consistency", consistency_node)
    g.add_node("compliance", compliance_node)
    g.add_node("persist", persist_node)
    g.add_node("finish", finish_node)
    g.add_node("fail", fail_node)

    g.add_edge(START, "collect")
    g.add_conditional_edges(
        "collect", _ok_or_fail("bible"), {"bible": "bible", "fail": "fail"}
    )
    g.add_conditional_edges(
        "bible", _ok_or_fail("plot_tree"), {"plot_tree": "plot_tree", "fail": "fail"}
    )
    g.add_conditional_edges(
        "plot_tree", _ok_or_fail("script"), {"script": "script", "fail": "fail"}
    )
    g.add_conditional_edges(
        "script",
        _ok_or_fail("consistency"),
        {"consistency": "consistency", "fail": "fail"},
    )
    g.add_conditional_edges(
        "consistency",
        _ok_or_fail("compliance"),
        {"compliance": "compliance", "fail": "fail"},
    )
    g.add_conditional_edges(
        "compliance",
        lambda s: "persist" if s.get("stage") == "persist" else "fail",
        {"persist": "persist", "fail": "fail"},
    )
    g.add_conditional_edges(
        "persist",
        lambda s: "finish" if s.get("stage") == "finish" else "fail",
        {"finish": "finish", "fail": "fail"},
    )
    g.add_conditional_edges(
        "finish",
        lambda s: "__end__" if s.get("fission_done") else "fail",
        {"__end__": END, "fail": "fail"},
    )
    g.add_edge("fail", END)
    return g.compile()


async def run_fission_graph(story_id: str, *, include_produce: bool = False) -> None:
    repo = StoryRepository()
    meta = repo.load_meta(story_id)
    repo.append_event(
        story_id,
        phase=FissionPhase.collect,
        type="phase",
        message="开始全流程（LangGraph：collect→bible→plot_tree→script→consistency→…）",
        payload={
            "inspiration": meta.inspiration[:120],
            "include_produce": include_produce,
        },
    )
    graph = build_fission_graph() if include_produce else _build_fission_only_graph()
    initial: FissionGraphState = {
        "story_id": story_id,
        "stage": "collect",
        "fission_done": False,
        "produce_done": False,
        "done": False,
        "error": None,
    }
    final = await graph.ainvoke(initial)
    ok = bool(final.get("done")) if include_produce else bool(final.get("fission_done"))
    if not ok:
        err = final.get("error") or "流程未完成"
        repo.append_event(
            story_id,
            phase=FissionPhase.failed,
            type="error",
            message=err,
        )
        m = repo.load_meta(story_id)
        if m.phase != FissionPhase.done:
            m.phase = FissionPhase.failed
            repo.save_meta(m)
        raise RuntimeError(err)
    await repo.sync_story_row(story_id)
