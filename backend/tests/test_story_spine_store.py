from __future__ import annotations

from backend.app.services.story_spine_store import (
    completion_point_reached,
    validate_mainline_spine_coverage,
)
from backend.app.models.story_spine import StorySpine


def test_validate_mainline_multi_nodes_per_event() -> None:
    events = ["醒来", "交锋", "结盟", "决战", "称霸狗群", "接受身份"]
    refs = ["醒来", "交锋", "交锋", "结盟", "决战", "称霸狗群", "接受身份"]
    assert validate_mainline_spine_coverage(refs, events, finalize=True) == []


def test_validate_mainline_rejects_skip() -> None:
    events = ["醒来", "交锋", "结盟", "决战", "称霸狗群", "接受身份"]
    refs = ["醒来", "结盟"]
    issues = validate_mainline_spine_coverage(refs, events, finalize=True)
    assert any("跳过" in x for x in issues)


def test_completion_point_reached() -> None:
    assert completion_point_reached(
        StorySpine(
            protagonist="x",
            completion_point="称霸城市狗群",
            key_events=["a", "b", "c", "d", "e", "称霸城市狗群"],
        ),
        "主角终于称霸城市狗群，众犬臣服",
    )
