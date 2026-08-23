from __future__ import annotations

from backend.app.models.fission_config import FissionConfig
from backend.app.models.plot_tree import PlotTreeNode, PlotTreeOutline
from backend.app.services.plot_tree_fork_slots import (
    build_slot_fill_plan,
    fork_slot_catalog_prompt,
)
from backend.app.services.plot_tree_repair import (
    analyze_plot_tree_issues,
    build_plot_tree_repair_prompt,
    plot_tree_generation_fork_guide,
)


def test_generation_guide_has_slot_catalog() -> None:
    guide = plot_tree_generation_fork_guide()
    assert "方式分叉" in guide
    assert "fork_slot" in guide
    assert "填槽" in guide


def test_slot_fill_plan_for_linear_node() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="S02", type="branch", title="替幼犬挡一口", parent="S01"),
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
    plan = build_slot_fill_plan(issues["single_choice_nodes"])
    assert "S01" in plan
    assert "S02" in plan
    assert "method" in plan or "方式" in plan


def test_repair_prompt_slot_focus() -> None:
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
        key_events=["事件1"],
        slot_focus=True,
    )
    assert "必填空槽" in prompt
    assert "fork_slot" in prompt
    assert fork_slot_catalog_prompt()[:20] in prompt or "分叉维度库" in prompt
