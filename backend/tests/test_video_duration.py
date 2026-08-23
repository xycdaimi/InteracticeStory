from __future__ import annotations

import json

import pytest

from backend.app.agents.prompt_minimax import build_shot_user
from backend.app.services.video_duration import (
    clamp_duration,
    infer_duration_from_content,
    parse_shot_prompt_response,
    resolve_segment_duration,
)


def test_clamp_duration() -> None:
    assert clamp_duration(2) == 4
    assert clamp_duration(20) == 15
    assert clamp_duration(8) == 8


def test_infer_duration_prev_last_frame_shorter() -> None:
    short = infer_duration_from_content(
        summary="他拔剑格挡。",
        prompt_text="剑光一闪。",
        first_frame_source="prev_last_frame",
    )
    long = infer_duration_from_content(
        summary="他拔剑格挡。",
        prompt_text="剑光一闪。",
        first_frame_source="synthetic",
    )
    assert short <= long


def test_infer_duration_dialogue_and_ending() -> None:
    d = infer_duration_from_content(
        title="桃园誓约",
        summary="三人焚香拜天，齐声宣誓：不求同年同月同日生，但求同年同月同日死。",
        prompt_text="镜头缓缓推近，三人举杯。",
        node_kind="ending",
        first_frame_source="synthetic",
    )
    assert d >= 9


def test_parse_shot_prompt_response_json() -> None:
    raw = '{"prompt_text":"夜色中军营灯火通明","duration_seconds":11}'
    prompt, dur = parse_shot_prompt_response(raw)
    assert prompt == "夜色中军营灯火通明"
    assert dur == 11


def test_parse_shot_prompt_response_plain_text_fallback() -> None:
    prompt, dur = parse_shot_prompt_response(
        "军营夜色，火把摇曳。",
        summary="夜袭前夜",
        first_frame_source="synthetic",
    )
    assert "军营" in prompt
    assert 4 <= dur <= 15


def test_resolve_segment_duration_prefers_segment() -> None:
    seg = {"video_duration": 12, "first_frame_source": "synthetic"}
    shot = {"duration_seconds": 6, "prompt_text": "test"}
    assert resolve_segment_duration(seg, shot) == 12


def test_build_shot_user_uses_assembled_draft() -> None:
    draft = "【参考图】\n- 首帧：军营夜色\n\n第0~2s：刘备：「诸位且听我一言」。"
    user = build_shot_user(
        assembled_draft=draft,
        duration_seconds=8,
        inspiration="三国",
        continues_from_prev_shot=False,
    )
    assert "待润色初稿" in user
    assert "诸位且听我一言" in user
    assert "同场景" not in user
