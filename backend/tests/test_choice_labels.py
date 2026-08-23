from __future__ import annotations

from backend.app.services.choice_labels import validate_protagonist_choice_label


def test_rejects_vague_action_intent() -> None:
    assert validate_protagonist_choice_label("动作") is not None
    assert validate_protagonist_choice_label("意图") is not None


def test_accepts_concrete_protagonist_line() -> None:
    assert validate_protagonist_choice_label("「云长，今夜便动身」") is None
    assert validate_protagonist_choice_label("低吼着挡在铁门前，不让别的狗靠近") is None
    assert validate_protagonist_choice_label("低声警告头犬退后三步") is None
    assert validate_protagonist_choice_label("转身叼走肉骨躲开狗群") is None


def test_rejects_very_short_vague() -> None:
    assert validate_protagonist_choice_label("走开") is not None
