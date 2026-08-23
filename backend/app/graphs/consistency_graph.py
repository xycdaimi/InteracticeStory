from __future__ import annotations

from backend.app.models.enums import FissionPhase
from backend.app.services.consistency_check import check_consistency
from backend.app.services.story_repository import StoryRepository


async def run_consistency_graph(story_id: str) -> None:
    """Pass4：程序结构校验（不做 DAG AI 多轮删改）。"""
    repo = StoryRepository()
    meta = repo.load_meta(story_id)
    meta.phase = FissionPhase.consistency
    repo.save_meta(meta)
    repo.append_event(
        story_id,
        phase=FissionPhase.consistency,
        type="phase",
        message="Pass4：结构一致性校验",
    )

    issues = check_consistency(story_id)
    if issues:
        messages = [
            f"[{i.get('code')}] {i.get('node_id')}: {i.get('message')}"
            for i in issues
        ]
        joined = "；".join(messages[:30])
        repo.append_event(
            story_id,
            phase=FissionPhase.consistency,
            type="error",
            message=f"一致性校验失败：{joined}",
            payload={"issues": issues[:50]},
        )
        raise RuntimeError(f"一致性校验失败：{joined}")

    graph = repo.load_graph(story_id)
    repo.append_event(
        story_id,
        phase=FissionPhase.consistency,
        type="phase",
        message="Pass4 一致性校验通过",
        payload={"plot_line_count": graph.line_count},
    )
