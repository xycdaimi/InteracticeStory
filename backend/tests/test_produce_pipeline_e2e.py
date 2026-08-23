from __future__ import annotations

import pytest

from backend.app.services.segment_plan import topo_waves


def test_frame_continuity_wave_order() -> None:
    """同场景链 A→B→C 必须分三波；独立入口与 A 同波。"""
    segments = [
        {"segment_id": "seg_root_a", "first_frame_source": "synthetic"},
        {
            "segment_id": "seg_a_b",
            "first_frame_source": "prev_last_frame",
            "pred_segment_id": "seg_root_a",
        },
        {
            "segment_id": "seg_b_c",
            "first_frame_source": "prev_last_frame",
            "pred_segment_id": "seg_a_b",
        },
        {"segment_id": "seg_root_x", "first_frame_source": "synthetic"},
    ]
    waves = topo_waves(segments)
    assert len(waves) == 3
    wave0 = {s["segment_id"] for s in waves[0]}
    assert wave0 == {"seg_root_a", "seg_root_x"}
    assert [s["segment_id"] for s in waves[1]] == ["seg_a_b"]
    assert [s["segment_id"] for s in waves[2]] == ["seg_b_c"]
