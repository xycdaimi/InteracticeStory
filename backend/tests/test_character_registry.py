from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import NodeScript, StoryGraph, StoryNode
from backend.app.services.cast_extract import CharacterDraft
from backend.app.services.character_registry import (
    align_cast_with_scripts,
    build_character_slug_map,
    collect_script_character_tokens,
    match_token_to_character_id,
)


def _sample_script(**kwargs) -> NodeScript:
    return NodeScript.model_validate(
        {
            "duration_seconds": 8,
            "dramatic_state_in": "in",
            "dramatic_state_out": "out",
            "beats": [
                {
                    "t_start": 0,
                    "t_end": 4,
                    "shot": "中景",
                    "action": "对峙",
                    "dialogue": [
                        {"speaker": "family_member", "line": "你先冷静"},
                        {"speaker": "cat", "line": "我听得懂"},
                    ],
                },
                {
                    "t_start": 4,
                    "t_end": 8,
                    "shot": "近景",
                    "action": "回应",
                    "dialogue": [{"speaker": "owner", "line": "我相信你"}],
                },
            ],
            "visual_plan": {
                "first_frame": {
                    "required": True,
                    "depicts": "门缝光",
                    "covers_character_ids": ["owner"],
                },
                "character_refs": [{"character_id": "family_member"}],
                "hidden_or_pov_only_ids": [],
            },
            **kwargs,
        }
    )


def _cast() -> list[CharacterDraft]:
    return [
        CharacterDraft("c_0000", "会说话的猫", "橘猫", []),
        CharacterDraft("c_0001", "主人", "青年", []),
        CharacterDraft("c_0002", "家人", "中年人", []),
    ]


def test_match_family_member_slug() -> None:
    chars = _cast()
    assert match_token_to_character_id("family_member", chars) == "c_0002"
    assert match_token_to_character_id("owner", chars) == "c_0001"
    assert match_token_to_character_id("cat", chars, protagonist_id="c_0000") == "c_0000"


def test_align_cast_rewrites_script_ids() -> None:
    g = StoryGraph(
        story_id="s",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(
                id="n_a",
                kind=NodeKind.main,
                title="争执",
                script=_sample_script(),
            ),
        },
        edges=[],
        options=[],
    )
    chars, slug_map = align_cast_with_scripts(g, _cast(), protagonist_id="c_0000")
    assert slug_map["family_member"] == "c_0002"
    script = g.nodes["n_a"].script
    assert script is not None
    assert script.visual_plan.character_refs[0].character_id == "c_0002"
    assert script.visual_plan.first_frame.covers_character_ids == ["c_0001"]
    assert len(chars) == 3


def test_build_slug_map_for_prompt_lookup() -> None:
    g = StoryGraph(
        story_id="s",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(
                id="n_a",
                kind=NodeKind.main,
                title="x",
                script=_sample_script(),
            ),
        },
        edges=[],
        options=[],
    )
    slug_map = build_character_slug_map(
        collect_script_character_tokens(g), _cast(), protagonist_id="c_0000"
    )
    assert slug_map["family_member"] == "c_0002"
