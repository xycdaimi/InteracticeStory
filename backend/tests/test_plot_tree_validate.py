from __future__ import annotations

from backend.app.models.fission_config import FissionConfig
from backend.app.models.plot_tree import PlotTreeEdge, PlotTreeNode, PlotTreeOutline
from backend.app.services.plot_tree_validate import (
    build_plot_tree_graph,
    estimate_plot_path_count,
    normalize_plot_tree_outline,
    plot_tree_has_cycle,
    max_choice_fanout,
    validate_plot_tree,
)


def _cfg(**kwargs) -> FissionConfig:
    params = {"branch_depth": 3}
    params.update(kwargs)
    return FissionConfig(**params)


def test_linear_spine_zero_fanout() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="S02", type="branch", title="中", parent="S01"),
            PlotTreeNode(id="S03", type="branch", title="末", parent="S02"),
            PlotTreeNode(
                id="END",
                type="ending",
                title="结",
                parent="S03",
                outcome="completed",
            ),
        ],
        edges=[],
    )
    graph, errs = build_plot_tree_graph(outline)
    assert not errs
    assert max_choice_fanout(graph) == 1
    val_errs = validate_plot_tree(outline, _cfg())
    assert any("仅有 1 个选项" in e for e in val_errs)


def test_branch_depth_is_max_children_per_node() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="A", type="branch", title="A", parent="S01"),
            PlotTreeNode(id="B", type="branch", title="B", parent="S01"),
            PlotTreeNode(id="C", type="branch", title="C", parent="S01"),
            PlotTreeNode(id="D", type="branch", title="D", parent="S01"),
            PlotTreeNode(
                id="E1",
                type="ending",
                title="结1",
                parent="A",
                outcome="completed",
            ),
            PlotTreeNode(
                id="E2",
                type="ending",
                title="结2",
                parent="B",
                outcome="failed",
            ),
            PlotTreeNode(
                id="E3",
                type="ending",
                title="结3",
                parent="C",
                outcome="near",
            ),
            PlotTreeNode(
                id="E4",
                type="ending",
                title="结4",
                parent="D",
                outcome="failed",
            ),
        ],
        edges=[],
    )
    graph, _ = build_plot_tree_graph(outline)
    assert max_choice_fanout(graph) == 4
    errs = validate_plot_tree(outline, _cfg(branch_depth=3))
    assert any("子分支数" in e and "branch_depth" in e for e in errs)
    # 多层分叉只要每层 ≤3 即可，不限制「分叉层数」
    outline2 = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="A", type="branch", title="A", parent="S01"),
            PlotTreeNode(id="B", type="branch", title="B", parent="S01"),
            PlotTreeNode(id="A1", type="branch", title="A1", parent="A"),
            PlotTreeNode(id="A2", type="branch", title="A2", parent="A"),
            PlotTreeNode(id="A3", type="branch", title="A3", parent="A"),
            PlotTreeNode(id="B1", type="branch", title="B1", parent="B"),
            PlotTreeNode(id="B2", type="branch", title="B2", parent="B"),
            PlotTreeNode(
                id="E1",
                type="ending",
                title="结1",
                parent="A1",
                outcome="completed",
            ),
            PlotTreeNode(
                id="E1b",
                type="ending",
                title="结1b",
                parent="A1",
                outcome="near",
            ),
            PlotTreeNode(
                id="E2",
                type="ending",
                title="结2",
                parent="A2",
                outcome="failed",
            ),
            PlotTreeNode(
                id="E2b",
                type="ending",
                title="结2b",
                parent="A2",
                outcome="failed",
            ),
            PlotTreeNode(
                id="E3",
                type="ending",
                title="结3",
                parent="A3",
                outcome="near",
            ),
            PlotTreeNode(
                id="E3b",
                type="ending",
                title="结3b",
                parent="A3",
                outcome="deferred",
            ),
            PlotTreeNode(
                id="E4",
                type="ending",
                title="结4",
                parent="B1",
                outcome="failed",
            ),
            PlotTreeNode(
                id="E4b",
                type="ending",
                title="结4b",
                parent="B1",
                outcome="near",
            ),
            PlotTreeNode(
                id="E5",
                type="ending",
                title="结5",
                parent="B2",
                outcome="failed",
            ),
            PlotTreeNode(
                id="E5b",
                type="ending",
                title="结5b",
                parent="B2",
                outcome="near",
            ),
        ],
        edges=[],
    )
    errs2 = validate_plot_tree(outline2, _cfg(branch_depth=3, min_paths=8))
    assert not any("branch_depth" in e and "子分支数" in e for e in errs2)


def test_normalize_parent_without_edge() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="S04B", type="branch", title="父", parent="S01"),
            PlotTreeNode(
                id="S05B",
                type="branch",
                title="子",
                parent="S04B",
                option_label="「继续」",
            ),
            PlotTreeNode(
                id="END",
                type="ending",
                title="结",
                parent="S05B",
                outcome="completed",
            ),
        ],
        edges=[
            PlotTreeEdge(**{"from": "S01", "to": "S04B", "label": "「走」"}),
            PlotTreeEdge(**{"from": "S05B", "to": "END", "label": "「结」"}),
        ],
    )
    fixed = normalize_plot_tree_outline(outline)
    pairs = {(e.from_id, e.to_id) for e in fixed.edges}
    assert ("S04B", "S05B") in pairs
    errs = validate_plot_tree(fixed, _cfg())
    assert not any("edges 中无对应边" in e for e in errs)


def test_cycle_does_not_recursion_error() -> None:
    """rejoin 形成环时须报结构错误，不能 maximum recursion depth exceeded。"""
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="A", type="branch", title="A", parent="S01"),
            PlotTreeNode(id="B", type="branch", title="B", parent="A", rejoin="A"),
            PlotTreeNode(
                id="END",
                type="ending",
                title="结",
                parent="B",
                outcome="completed",
            ),
        ],
        edges=[],
    )
    graph, _ = build_plot_tree_graph(outline)
    assert plot_tree_has_cycle(graph)
    assert estimate_plot_path_count(graph) == 0
    errs = validate_plot_tree(outline, _cfg())
    assert any("环" in e for e in errs)


def test_path_count_validation() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="A", type="branch", title="A", parent="S01"),
            PlotTreeNode(id="B", type="branch", title="B", parent="S01"),
            PlotTreeNode(
                id="E1",
                type="ending",
                title="结1",
                parent="A",
                outcome="completed",
            ),
            PlotTreeNode(
                id="E2",
                type="ending",
                title="结2",
                parent="B",
                outcome="failed",
            ),
        ],
        edges=[],
    )
    graph, _ = build_plot_tree_graph(outline)
    assert estimate_plot_path_count(graph) == 2
    errs = validate_plot_tree(outline, _cfg(min_paths=8))
    assert any("路径数" in e for e in errs)


def test_rejoin_not_counted_as_fork() -> None:
    outline = PlotTreeOutline(
        root="S01",
        nodes=[
            PlotTreeNode(id="S01", type="start", title="起"),
            PlotTreeNode(id="A", type="branch", title="绕路", parent="S01"),
            PlotTreeNode(id="S02", type="merge", title="汇合", parent="S01"),
            PlotTreeNode(
                id="END",
                type="ending",
                title="结",
                parent="S02",
                outcome="completed",
            ),
        ],
        edges=[
            PlotTreeEdge(**{"from": "S01", "to": "A", "label": "「绕路」"}),
            PlotTreeEdge(**{"from": "S01", "to": "S02", "label": "「直行」"}),
            PlotTreeEdge(**{"from": "S02", "to": "END", "label": "「结束」"}),
        ],
    )
    outline.nodes[1].rejoin = "S02"
    graph, _ = build_plot_tree_graph(outline)
    assert max_choice_fanout(graph) == 2
