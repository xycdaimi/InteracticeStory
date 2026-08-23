from __future__ import annotations

from backend.app.models.fission_config import FissionConfig
from backend.app.models.plot_tree import PlotTreeNode, PlotTreeOutline
from backend.app.services.plot_tree_repair import (
    analyze_plot_tree_issues,
    build_plot_tree_repair_prompt,
)


def test_analyze_single_choice_linear_chain() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="S02", type="branch", title="中", parent="S01"),
            PlotTreeNode(
                id="END",
                type="ending",
                title="结",
                parent="S02",
                outcome="completed",
            ),
        ],
        edges=[],
    )
    issues = analyze_plot_tree_issues(outline, FissionConfig(branch_depth=3))
    ids = {n["id"] for n in issues["single_choice_nodes"]}
    assert ids == {"S01", "S02"}


def test_repair_prompt_mentions_merge_and_parallel() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="A", type="branch", title="追气味", parent="S01"),
            PlotTreeNode(
                id="END",
                type="ending",
                title="完",
                parent="A",
                outcome="near",
            ),
        ],
        edges=[],
    )
    prompt = build_plot_tree_repair_prompt(
        outline=outline,
        errors=["节点 S01（起）仅有 1 个选项"],
        config=FissionConfig(min_paths=8, branch_depth=3),
        protagonist="阿呆",
        completion_point="称霸狗群",
        key_events=["事件1", "事件2", "事件3", "事件4", "事件5", "称霸狗群"],
    )
    assert "汇合" in prompt or "填槽" in prompt
    assert "并行" in prompt or "方式" in prompt
    assert "追气味" in prompt
