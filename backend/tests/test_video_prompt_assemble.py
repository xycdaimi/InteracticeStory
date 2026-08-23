from __future__ import annotations

import pytest

from backend.app.models.story_graph import NodeScript
from backend.app.services.video_prompt_assemble import (
    assemble_prompt_from_script,
    resolve_ref_bindings,
)


def _script(**vp_overrides) -> NodeScript:
    vp = {
        "first_frame": {
            "required": True,
            "depicts": "敌将立于阵前",
            "covers_character_ids": ["c_enemy"],
        },
        "character_refs": [{"character_id": "c_leader"}],
        "scene_ref": None,
        "hidden_or_pov_only_ids": ["c_pov"],
    }
    vp.update(vp_overrides)
    return NodeScript.model_validate(
        {
            "duration_seconds": 8,
            "dramatic_state_in": "对峙",
            "dramatic_state_out": "静默",
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
                    "shot": "旋镜",
                    "action": "看主帅",
                    "dialogue": [{"speaker": "主帅", "line": "可有人出战"}],
                    "pov": "c_pov",
                },
            ],
            "visual_plan": vp,
        }
    )


def test_resolve_skips_covered_and_pov() -> None:
    script = _script()
    bindings = resolve_ref_bindings(
        script,
        first_frame_path="assets/frames/a.png",
        character_images={
            "c_enemy": "assets/characters/c_enemy.png",
            "c_leader": "assets/characters/c_leader.png",
            "c_pov": "assets/characters/c_pov.png",
        },
        character_names={"c_leader": "主帅"},
    )
    roles = [(b.role, b.character_id) for b in bindings]
    assert ("first_frame", None) in roles
    assert ("character", "c_leader") in roles
    assert ("character", "c_enemy") not in roles
    assert ("character", "c_pov") not in roles


def test_assemble_timed_prompt() -> None:
    script = _script()
    bindings = resolve_ref_bindings(
        script,
        first_frame_path="assets/frames/a.png",
        character_images={"c_leader": "assets/characters/c_leader.png"},
        character_names={"c_leader": "主帅"},
    )
    text = assemble_prompt_from_script(
        script,
        bindings,
        pov_names={"c_pov": "视角主角"},
    )
    assert "【参考图】" in text
    assert "首帧：敌将立于阵前" in text
    assert "定妆：主帅" in text
    assert "第0~2s：" in text
    assert "谁敢一战" in text
    assert "转到视角主角的主观视角" in text


def test_missing_first_frame_raises() -> None:
    script = _script()
    with pytest.raises(RuntimeError, match="首帧"):
        resolve_ref_bindings(script, first_frame_path=None, character_images={})


def test_chain_shot_skips_first_frame_binding_until_path_ready() -> None:
    script = _script()
    bindings = resolve_ref_bindings(
        script,
        first_frame_path=None,
        character_images={"c_leader": "assets/characters/c_leader.png"},
        continues_from_prev_shot=True,
    )
    assert all(b.role != "first_frame" for b in bindings)
    assert any(b.role == "character" for b in bindings)
