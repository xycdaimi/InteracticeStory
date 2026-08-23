from __future__ import annotations

from backend.app.graphs.fission_graph import run_fission_graph


async def run_fission(story_id: str, *, include_produce: bool = False) -> None:
    """裂变入口。仅 CLI 全流水线时传 include_produce=True；Web 裂变后须手动点「开始生产」。"""
    await run_fission_graph(story_id, include_produce=include_produce)
