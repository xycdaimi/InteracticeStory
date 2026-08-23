from __future__ import annotations

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import (
    NodeScript,
    StoryEdge,
    StoryGraph,
    StoryNode,
    StoryOption,
)
from backend.app.services.plot_line_continuity import check_all_plot_lines


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


def test_merge_node_checked_per_plot_line_not_cross_parent() -> None:
    """汇合节点：只在该剧情线的上游父节点下校验，不拿其他线的父节点硬比。"""
    merge = StoryNode(
        id="c",
        kind=NodeKind.branch,
        title="汇合",
        script=_script(
            "父A状态结束；「从A来」",
            "汇合后",
            "「从A来」继续推进",
        ),
    )
    graph = StoryGraph(
        story_id="s",
        root_id="n_root",
        nodes={
            "n_root": StoryNode(id="n_root", kind=NodeKind.root, title="起"),
            "p1": StoryNode(
                id="p1",
                kind=NodeKind.main,
                title="父A",
                script=_script("起", "父A状态结束", "走A进入"),
            ),
            "p2": StoryNode(
                id="p2",
                kind=NodeKind.main,
                title="父B",
                script=_script("起", "父B完全不同状态", "走B进入"),
            ),
            "c": merge,
            "e": StoryNode(
                id="e",
                kind=NodeKind.ending,
                title="结",
                parent_id="c",
                outcome="completed",
                script=_script("汇合后", "结局", "结束"),
            ),
        },
        options=[
            StoryOption(id="o1", from_node_id="n_root", to_node_id="p1", label="走A"),
            StoryOption(id="o2", from_node_id="n_root", to_node_id="p2", label="走B"),
            StoryOption(id="o3", from_node_id="p1", to_node_id="c", label="「从A来」"),
            StoryOption(id="o4", from_node_id="p2", to_node_id="c", label="「从B来」"),
            StoryOption(id="o5", from_node_id="c", to_node_id="e", label="结束"),
        ],
        edges=[
            StoryEdge(id="e1", source="n_root", target="p1"),
            StoryEdge(id="e2", source="n_root", target="p2"),
            StoryEdge(id="e3", source="p1", target="c"),
            StoryEdge(id="e4", source="p2", target="c"),
            StoryEdge(id="e5", source="c", target="e"),
        ],
    )
    issues = check_all_plot_lines(graph)
    codes = {(i.plot_line_id, i.code, i.node_id) for i in issues}

    # 线 pl_0001: root→p1→c 应通过
    assert ("pl_0001", "STATE_BREAK", "c") not in codes
    assert ("pl_0001", "CHOICE_NOT_GROUNDED", "c") not in codes

    # 线 pl_0002: root→p2→c 应对 c 报错（script 只接了父A）
    assert ("pl_0002", "STATE_BREAK", "c") in codes
    assert ("pl_0002", "CHOICE_NOT_GROUNDED", "c") in codes

    # 不应出现无 plot_line_id 的混杂报错
    assert all(i.plot_line_id for i in issues if i.code in {"STATE_BREAK", "CHOICE_NOT_GROUNDED"})
