from __future__ import annotations

from backend.app.ai.dashscope_omni import _normalize_qc_model, _parse_qc_json, build_review_video_user_text


def test_normalize_qc_model() -> None:
    assert _normalize_qc_model("Qwen3-Omni-Flash") == "qwen3-omni-flash"


def test_qc_user_text_contains_scope_and_forbidden() -> None:
    text = build_review_video_user_text("ctx")
    assert "【审查范围】" in text
    assert "不要评价" in text or "不要与前驱" in text
    assert "连贯" in text  # 出现在禁止理由说明中
    assert "片段间" in text or "前驱" in text
    assert "ctx" in text


def test_parse_qc_json_pass() -> None:
    out = _parse_qc_json('{"status":"pass","reasons":[]}')
    assert out["status"] == "pass"


def test_parse_qc_json_fail_with_reasons() -> None:
    out = _parse_qc_json('说明\n{"status":"fail","reasons":["人设崩"]}')
    assert out["status"] == "fail"
    assert "人设崩" in out["reasons"][0]
