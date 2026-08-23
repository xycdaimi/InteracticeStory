from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from backend.app.models.enums import FissionPhase
from backend.app.services.produce_state import load_blueprint, save_blueprint
from backend.app.services.segment_plan import PRODUCE_TIER_ON_DEMAND
from backend.app.services.story_repository import StoryRepository
from backend.app.services.video_pipeline import (
    generate_segment_video,
    qc_and_maybe_regen,
)

logger = logging.getLogger(__name__)


def _find_segment(blueprint: dict[str, Any], segment_id: str) -> dict[str, Any]:
    for seg in blueprint.get("segments") or []:
        if seg["segment_id"] == segment_id:
            return seg
    raise HTTPException(status_code=404, detail="segment not found")


async def produce_segment_on_demand(
    story_id: str,
    segment_id: str,
    *,
    repo: StoryRepository | None = None,
    run_qc: bool = True,
) -> dict[str, Any]:
    """游玩时按需生成单个片段（首帧依赖应已由预生产片段提供）。"""
    repo = repo or StoryRepository()
    blueprint = load_blueprint(story_id)
    seg = _find_segment(blueprint, segment_id)

    if seg.get("video_status") == "ready" and seg.get("video_path"):
        return {"segment_id": segment_id, "status": "ready", "video_path": seg["video_path"]}

    if seg.get("produce_tier") != PRODUCE_TIER_ON_DEMAND and seg.get("video_status") == "deferred":
        pass  # 预生产片段若未完成，也允许补跑

    if seg.get("first_frame_source") == "prev_last_frame" and not seg.get("first_frame_path"):
        raise HTTPException(
            status_code=400,
            detail="前驱视频/尾帧未就绪，请先完成预生产前驱片段",
        )

    if not seg.get("first_frame_path"):
        raise HTTPException(
            status_code=400,
            detail="首帧未就绪，请先游玩至前驱片段或等待预生产完成",
        )

    await generate_segment_video(story_id, seg)
    save_blueprint(story_id, blueprint)

    qc_result: dict[str, Any] | None = None
    if run_qc:
        qc_result = await qc_and_maybe_regen(story_id, seg, repo=repo)
        save_blueprint(story_id, blueprint)

    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="video",
        message=f"按需出片完成：{segment_id}",
        payload={"segment_id": segment_id, "qc": qc_result},
    )
    return {
        "segment_id": segment_id,
        "status": seg.get("video_status"),
        "video_path": seg.get("video_path"),
        "qc_status": seg.get("qc_status"),
    }
