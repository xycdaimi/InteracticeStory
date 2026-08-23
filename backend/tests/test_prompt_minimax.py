from __future__ import annotations

from backend.app.agents.prompt_minimax import build_shot_user, ensure_lines_preserved


def test_build_shot_user_uses_assembled_draft() -> None:
    draft = "【参考图】\n- 首帧：阵前\n\n第0~2s：敌将：「谁敢一战」。"
    text = build_shot_user(
        assembled_draft=draft,
        duration_seconds=8,
        inspiration="测试",
        continues_from_prev_shot=False,
    )
    assert "待润色初稿" in text
    assert "谁敢一战" in text
    assert "同场景" not in text


def test_ensure_lines_preserved() -> None:
    draft = "第0~2s：甲：『你好』。"
    assert ensure_lines_preserved(draft, "润色后甲：『你好』。")
    assert not ensure_lines_preserved(draft, "润色后没有原句")
