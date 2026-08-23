from __future__ import annotations

from backend.app.services.script_sanitize import sanitize_script_dict


def test_sanitize_coerces_first_frame_required_to_bool() -> None:
    raw = {
        "duration_seconds": "8",
        "dramatic_state_in": "a",
        "dramatic_state_out": "b",
        "beats": [
            {"t_start": 0, "t_end": 4, "dialogue": [{"speaker": "甲", "line": "x"}]},
            {"t_start": 4, "t_end": 8, "dialogue": [{"speaker": "甲", "line": "y"}]},
        ],
        "visual_plan": {
            "first_frame": {"required": "true", "depicts": "场景"},
            "character_refs": [],
        },
    }
    out = sanitize_script_dict(raw)
    assert out["duration_seconds"] == 8
    assert out["visual_plan"]["first_frame"]["required"] is True


def test_sanitize_strips_covers_refs_overlap() -> None:
    raw = {
        "duration_seconds": 8,
        "dramatic_state_in": "a",
        "dramatic_state_out": "b",
        "beats": [
            {"t_start": 0, "t_end": 4, "dialogue": [{"speaker": "甲", "line": "x"}]},
            {"t_start": 4, "t_end": 8, "dialogue": [{"speaker": "甲", "line": "y"}]},
        ],
        "visual_plan": {
            "first_frame": {
                "required": True,
                "depicts": "场面",
                "covers_character_ids": ["hero", "rival"],
            },
            "character_refs": ["hero", {"character_id": "rival"}, {"character_id": "npc"}],
        },
    }
    out = sanitize_script_dict(raw)
    refs = {r["character_id"] for r in out["visual_plan"]["character_refs"]}
    covers = set(out["visual_plan"]["first_frame"]["covers_character_ids"])
    assert refs == {"npc"}
    assert covers == {"hero", "rival"}
    assert not (covers & refs)
