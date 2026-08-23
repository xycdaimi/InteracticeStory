from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import (
    NodeScript,
    StoryGraph,
    StoryNode,
    StoryOption,
)
from backend.app.services.script_continuity import check_parent_children


def _script(state_in: str, state_out: str, opening: str) -> NodeScript:
    return NodeScript.model_validate(
        {
            "duration_seconds": 8,
            "dramatic_state_in": state_in,
            "dramatic_state_out": state_out,
            "beats": [
                {
                    "t_start": 0,
                    "t_end": 3,
                    "shot": "中景",
                    "action": opening,
                    "dialogue": [{"speaker": "角色", "line": opening}],
                },
                {
                    "t_start": 3,
                    "t_end": 6,
                    "shot": "近景",
                    "action": "收束",
                    "dialogue": [{"speaker": "角色", "line": "完"}],
                },
            ],
            "visual_plan": {
                "first_frame": {
                    "required": True,
                    "depicts": "建立",
                    "covers_character_ids": [],
                },
                "character_refs": [],
                "hidden_or_pov_only_ids": [],
            },
        }
    )


def test_state_break_and_choice_grounded() -> None:
    parent = StoryNode(
        id="n_p",
        kind=NodeKind.main,
        title="父",
        script=_script("入", "全场静默等应答", "父拍"),
    )
    ok_child = StoryNode(
        id="n_ok",
        kind=NodeKind.branch,
        title="子好",
        script=_script("全场静默等应答；独自上前", "子结束", "独自上前领命"),
    )
    bad_child = StoryNode(
        id="n_bad",
        kind=NodeKind.branch,
        title="子坏",
        script=_script("完全无关的状态", "子结束", "环顾四周"),
    )
    graph = StoryGraph(
        story_id="s",
        root_id="n_p",
        nodes={"n_p": parent, "n_ok": ok_child, "n_bad": bad_child},
        options=[
            StoryOption(id="o1", from_node_id="n_p", to_node_id="n_ok", label="独自上前领命"),
            StoryOption(id="o2", from_node_id="n_p", to_node_id="n_bad", label="缄默不出身"),
        ],
        edges=[],
    )
    issues = check_parent_children(graph, "n_p")
    codes = {(i.code, i.node_id) for i in issues}
    assert ("STATE_BREAK", "n_bad") in codes
    assert ("CHOICE_NOT_GROUNDED", "n_bad") in codes
    assert ("STATE_BREAK", "n_ok") not in codes
