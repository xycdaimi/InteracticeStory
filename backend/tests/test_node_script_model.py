from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.models.story_graph import (
    CharacterRefNeed,
    DialogueLine,
    FirstFramePlan,
    NodeScript,
    ScriptBeat,
    StoryNode,
    VisualPlan,
    summary_from_script,
)
from backend.app.models.enums import NodeKind


def _valid_script(**overrides) -> NodeScript:
    data = {
        "duration_seconds": 8,
        "dramatic_state_in": "对峙开始",
        "dramatic_state_out": "全场静默等应答",
        "beats": [
            {
                "t_start": 0,
                "t_end": 2,
                "shot": "近景",
                "action": "叫阵",
                "dialogue": [{"speaker": "敌将", "line": "谁敢一战"}],
            },
            {
                "t_start": 2,
                "t_end": 5,
                "shot": "主观视角",
                "action": "主帅环视",
                "dialogue": [{"speaker": "主帅", "line": "可有人出战"}],
                "pov": "c_pov",
            },
        ],
        "visual_plan": {
            "first_frame": {
                "required": True,
                "depicts": "敌将立于阵前",
                "covers_character_ids": ["c_enemy"],
            },
            "character_refs": [{"character_id": "c_leader"}],
            "scene_ref": None,
            "hidden_or_pov_only_ids": ["c_pov"],
        },
    }
    data.update(overrides)
    return NodeScript.model_validate(data)


def test_node_script_round_trip() -> None:
    script = _valid_script()
    node = StoryNode(
        id="n_a",
        kind=NodeKind.main,
        title="对峙",
        summary=summary_from_script(script),
        script=script,
    )
    raw = node.model_dump()
    restored = StoryNode.model_validate(raw)
    assert restored.script is not None
    assert restored.script.beats[0].dialogue[0].line == "谁敢一战"
    assert restored.summary == "全场静默等应答"


def test_visual_plan_auto_strips_overlap_in_refs() -> None:
    script = _valid_script(
        visual_plan={
            "first_frame": {
                "required": True,
                "depicts": "敌将",
                "covers_character_ids": ["c_enemy"],
            },
            "character_refs": [{"character_id": "c_enemy"}, {"character_id": "c_leader"}],
            "hidden_or_pov_only_ids": [],
        }
    )
    ref_ids = {r.character_id for r in script.visual_plan.character_refs}
    assert "c_enemy" not in ref_ids
    assert "c_leader" in ref_ids


def test_visual_plan_auto_strips_hidden_in_refs() -> None:
    script = _valid_script(
        visual_plan={
            "first_frame": {
                "required": True,
                "depicts": "敌将",
                "covers_character_ids": [],
            },
            "character_refs": [{"character_id": "c_pov"}, {"character_id": "c_leader"}],
            "hidden_or_pov_only_ids": ["c_pov"],
        }
    )
    ref_ids = {r.character_id for r in script.visual_plan.character_refs}
    assert "c_pov" not in ref_ids
    assert "c_leader" in ref_ids


def test_requires_dialogue() -> None:
    with pytest.raises(ValidationError):
        NodeScript.model_validate(
            {
                "duration_seconds": 8,
                "dramatic_state_in": "a",
                "dramatic_state_out": "b",
                "beats": [
                    {"t_start": 0, "t_end": 2, "shot": "a", "action": "b", "dialogue": []},
                    {"t_start": 2, "t_end": 4, "shot": "c", "action": "d", "dialogue": []},
                ],
                "visual_plan": {
                    "first_frame": {"required": True, "depicts": "x", "covers_character_ids": []},
                    "character_refs": [],
                    "hidden_or_pov_only_ids": [],
                },
            }
        )


def test_old_node_without_script_loads() -> None:
    node = StoryNode.model_validate(
        {"id": "n_root", "kind": "root", "title": "起", "summary": "灵感"}
    )
    assert node.script is None
