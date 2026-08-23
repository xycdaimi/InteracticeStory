from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryEdge, StoryGraph, StoryNode
from backend.app.services.cast_extract import (
    build_cast_user,
    narrative_node_ids,
    parse_cast_payload,
)


def test_build_cast_user_uses_indices_not_node_ids() -> None:
    g = StoryGraph(
        story_id="s",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_secret": StoryNode(id="n_secret", kind=NodeKind.main, title="遇"),
        },
        edges=[],
    )
    text = build_cast_user("桃园", g)
    assert "[0]" in text
    assert "n_secret" not in text
    assert "定妆" not in text  # 约束在 system，user 里只提醒不写剧情
    assert "勿写剧情" in text


def test_parse_cast_payload_assigns_ids_in_code() -> None:
    g = StoryGraph(
        story_id="s",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="遇", parent_id="n_root"),
        },
        edges=[StoryEdge(id="e1", source="n_root", target="n_a")],
    )
    assert narrative_node_ids(g) == ["n_a"]

    chars, scenes, binds, protagonist_id = parse_cast_payload(
        {
            "protagonist_index": 0,
            "characters": [
                {
                    "name": "刘备",
                    "appearance_prompt": "白袍青年",
                    "traits": ["仁"],
                }
            ],
            "scenes": [{"name": "桃园", "visual_prompt": "桃花林"}],
            "bindings": [
                {"node_index": 0, "character_indices": [0], "scene_index": 0},
            ],
        },
        g,
    )
    assert chars[0].character_id == "c_0000"
    assert scenes[0].scene_id == "s_0000"
    assert binds[0].node_id == "n_a"
    assert binds[0].character_ids == ["c_0000"]
    assert binds[0].scene_id == "s_0000"
    assert protagonist_id == "c_0000"


def test_parse_cast_payload_skips_invalid_node_index() -> None:
    g = StoryGraph(
        story_id="s",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="遇"),
        },
        edges=[],
    )
    _, scenes, binds, _ = parse_cast_payload(
        {
            "characters": [],
            "scenes": [{"name": "桃园", "visual_prompt": "桃花"}],
            "bindings": [
                {"node_index": 99, "character_indices": [], "scene_index": 0},
                {"node_index": 0, "character_indices": [], "scene_index": 0},
            ],
        },
        g,
    )
    by_node = {b.node_id: b for b in binds}
    assert len(by_node) == 1
    assert by_node["n_a"].scene_id == "s_0000"
