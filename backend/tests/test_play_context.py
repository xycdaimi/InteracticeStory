from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph, StoryNode, StoryOption
from backend.app.services.play_context import build_node_play_context, incoming_choice


def test_incoming_choice() -> None:
    g = StoryGraph(
        story_id="s",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="遇", summary="遇见关羽"),
            "n_b": StoryNode(id="n_b", kind=NodeKind.main, title="议", summary="商议大事"),
        },
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="n_a", label="前往集市打听消息"),
            StoryOption(id="o2", from_node_id="n_a", to_node_id="n_b", label="「云长，今夜便动身」"),
        ],
    )
    label, from_title, from_summary = incoming_choice(g, "n_b")
    assert label == "「云长，今夜便动身」"
    assert from_title == "遇"
    assert "关羽" in from_summary


def test_build_node_play_context_protagonist() -> None:
    g = StoryGraph(
        story_id="s",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "n_a": StoryNode(id="n_a", kind=NodeKind.main, title="盟", summary="结盟"),
        },
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="n_a", label="向袁绍请战"),
        ],
    )
    blueprint = {
        "protagonist_character_id": "c_0000",
        "characters": [{"character_id": "c_0000", "name": "曹操"}],
    }
    ctx = build_node_play_context(graph=g, blueprint=blueprint, node_id="n_a")
    assert ctx["protagonist_name"] == "曹操"
    assert ctx["player_choice"] == "向袁绍请战"
