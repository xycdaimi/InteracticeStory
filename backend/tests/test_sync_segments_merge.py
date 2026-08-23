from __future__ import annotations

from backend.app.services.asset_pipeline import merge_segment_state


def test_merge_preserves_video_path() -> None:
    old = {
        "segment_id": "seg_a_b",
        "video_path": "assets/videos/seg_a_b.mp4",
        "video_status": "ready",
        "qc_status": "pass",
        "first_frame_path": "assets/frames/seg_a_b_first.png",
    }
    new = {
        "segment_id": "seg_a_b",
        "video_path": None,
        "video_status": "pending",
        "qc_status": "pending",
        "first_frame_path": None,
        "first_frame_source": "synthetic",
    }
    merged = merge_segment_state(old, new)
    assert merged["video_path"] == "assets/videos/seg_a_b.mp4"
    assert merged["video_status"] == "ready"
    assert merged["qc_status"] == "pass"
    assert merged["first_frame_path"] == "assets/frames/seg_a_b_first.png"


def test_merge_new_segment_defaults() -> None:
    new = {
        "segment_id": "seg_x_y",
        "first_frame_source": "synthetic",
        "video_status": "pending",
    }
    merged = merge_segment_state(None, new)
    assert merged["segment_id"] == "seg_x_y"
    assert merged.get("video_path") is None


def test_merge_preserves_ready_continuity() -> None:
    old = {
        "video_status": "ready",
        "continues_from_prev_shot": True,
        "continuity_reason": "LLM:连续对白",
        "first_frame_source": "prev_last_frame",
    }
    new = {
        "continues_from_prev_shot": False,
        "continuity_reason": None,
        "first_frame_source": "synthetic",
        "video_status": "pending",
    }
    merged = merge_segment_state(old, new)
    assert merged["continues_from_prev_shot"] is True
    assert merged["continuity_reason"] == "LLM:连续对白"
    assert merged["first_frame_source"] == "prev_last_frame"
