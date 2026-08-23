from __future__ import annotations

import json
from typing import Any

from backend.app.models.fission_config import FissionConfig
from backend.app.models.plot_tree import PlotTreeOutline
from backend.app.services.plot_tree_fork_slots import (
    build_slot_batch_repair_prompt,
    fork_slot_catalog_prompt,
    fork_slot_node_schema_hint,
)
from backend.app.services.plot_tree_validate import (
    build_plot_tree_graph,
    estimate_plot_path_count,
)


def _choice_children(graph, nid: str) -> list[str]:
    return list(dict.fromkeys(graph.choice_children.get(nid) or []))


def analyze_plot_tree_issues(
    outline: PlotTreeOutline,
    config: FissionConfig,
) -> dict[str, Any]:
    """提取供 LLM 修复用的结构化问题清单。"""
    graph, build_errs = build_plot_tree_graph(outline)
    single_choice: list[dict[str, Any]] = []
    if not build_errs:
        for nid, node in graph.by_id.items():
            if node.type == "ending":
                continue
            kids = _choice_children(graph, nid)
            if len(kids) >= 2:
                continue
            child_info = []
            for kid in kids:
                c = graph.by_id[kid]
                child_info.append(
                    {
                        "id": kid,
                        "type": c.type,
                        "title": c.title,
                        "summary": c.summary,
                        "fork_slot": getattr(c, "fork_slot", None),
                    }
                )
            single_choice.append(
                {
                    "id": nid,
                    "type": node.type,
                    "title": node.title,
                    "summary": node.summary,
                    "spine_event": node.spine_event,
                    "option_count": len(kids),
                    "children": child_info,
                }
            )

    path_count = estimate_plot_path_count(graph) if not build_errs else 0
    return {
        "build_errors": build_errs,
        "single_choice_nodes": single_choice,
        "path_count": path_count,
        "min_paths": int(config.min_paths),
        "branch_depth": int(config.branch_depth),
    }


def _plot_tree_hard_constraints(config: FissionConfig) -> str:
    et = config.ending_targets
    return (
        f"- branch_depth={config.branch_depth}：每个非 ending 节点的选择出边 ≤ {config.branch_depth}\n"
        f"- **硬结构**（非建议）：除 ending 外每个节点选择出边 ≥2；违反即无效\n"
        f"- 每个非 ending 节点须从 method/stance/info/risk 中至少 2 个不同维度各填 1 槽"
        f"（子节点 fork_slot 标明维度）\n"
        f"- 剧情线路径数 ≥ {config.min_paths}（root→ending 不同完整路径）\n"
        f"- 结局节点 ≥ {max(2, et.completed)} 个；outcome ∈ completed|near|failed|deferred\n"
        "- 子节点可被多个上游汇合（改 parent / 多入边 / merge+rejoin）\n"
        "- option_label 须为具体台词或可拍行动，用「」；禁止抽象词\n"
        "- summary 写「分叉容器」（可选维度），勿写成单动作场景推进\n"
        "- 禁止 script；只输出 PlotTreeOutline JSON\n"
    )


def build_plot_tree_repair_prompt(
    *,
    outline: PlotTreeOutline,
    errors: list[str],
    config: FissionConfig,
    protagonist: str,
    completion_point: str,
    key_events: list[str],
    slot_focus: bool = False,
) -> str:
    """根据校验失败与结构分析，生成剧情驱动的修复指令。"""
    analysis = analyze_plot_tree_issues(outline, config)
    events_block = "\n".join(f"{i + 1}. {ev}" for i, ev in enumerate(key_events))
    single_nodes = analysis["single_choice_nodes"]

    if slot_focus and single_nodes:
        return (
            build_slot_batch_repair_prompt(
                outline=outline,
                single_choice_nodes=single_nodes,
                errors=errors,
                config_min_paths=int(config.min_paths),
                path_count=analysis["path_count"],
            )
            + "\n\n## 主角\n"
            + protagonist
            + "\n## 完成点\n"
            + completion_point
            + "\n## key_events\n"
            + events_block
        )

    single_block = "无"
    if single_nodes:
        lines: list[str] = []
        for item in single_nodes:
            kids = item["children"]
            if not kids:
                child_desc = "（无子节点，须填 ≥2 槽）"
            elif len(kids) == 1 and kids[0]["type"] == "ending":
                c = kids[0]
                child_desc = (
                    f"唯一子节点为结局 {c['id']}「{c['title']}」"
                    f"（须再填一槽：平行路线或另一结局）"
                )
            elif len(kids) == 1:
                c = kids[0]
                fs = c.get("fork_slot") or "未标"
                child_desc = (
                    f"唯一子节点 {c['id']}「{c['title']}」fork_slot={fs}"
                    f"（线性链：须为**另一维度**再填 1 槽）"
                )
            else:
                child_desc = json.dumps(kids, ensure_ascii=False)
            lines.append(
                f"- {item['id']}（{item['type']}「{item['title']}」）"
                f"：{child_desc}；summary={item['summary']!r}"
            )
        single_block = "\n".join(lines)

    return (
        "上一版剧情树结构校验未通过。请按**填分叉槽位**修订整棵树，"
        "输出完整 PlotTreeOutline JSON（可增删改节点与边，尽量复用已有 id）。\n\n"
        "## 核心：填槽，不是「想分支」\n"
        "对每个单选项节点：先改 summary 为分叉容器，再从 method/stance/info/risk "
        "中选 ≥2 个不同维度，逐槽填 1 条出路；子节点标 fork_slot。\n\n"
        + fork_slot_catalog_prompt()
        + "\n\n## 校验错误\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\n## 单选项节点（须按槽位填空，禁止 AUTO/占位结局糊弄）\n"
        + single_block
        + "\n\n## 填槽修复步骤\n"
        "1. **方式(method)**：同一局面，换做法（偷听/硬闯/绕路…）\n"
        "2. **立场(stance)**：信/疑/合作/对抗\n"
        "3. **信息(info)**：先拿哪类线索、是否保留证据\n"
        "4. **风险(risk)**：安全推进 vs 冒险代价\n"
        "临近结局的唯一子节点为 ending 时：补一条平行路线（另一结局或经 1–2 事件再收束）。\n"
        "应汇合的情节：多上游指向同一子节点（merge+rejoin），勿重复同质节点。\n"
        "rejoin 只能指向下游汇合点，禁止指向上游形成环。\n"
        "路径不足：在已有分叉点加平行支路，勿写无意义的「岔路N」。\n\n"
        "## 硬约束\n"
        + _plot_tree_hard_constraints(config)
        + "\n## 主角\n"
        + protagonist
        + "\n## 完成点\n"
        + completion_point
        + "\n## key_events\n"
        + events_block
        + "\n\n## 当前路径数\n"
        + f"{analysis['path_count']} / 目标 {analysis['min_paths']}\n"
    )


def plot_tree_generation_fork_guide() -> str:
    """Pass2 初稿生成用的分叉槽位指引（与硬约束一起注入 prompt）。"""
    return (
        "## 生成方法：分叉容器 + 强制填槽（硬结构，非文学建议）\n"
        "禁止把故事写成顺滑单链。每个非 ending 节点先设计为「分叉容器」，"
        "再从 4 维中至少选 2 维各填 1 条出路。\n"
        "错误：「请为这个节点扩写多个分支。」\n"
        "正确：「本节点有 2~3 个强制空槽，请逐槽填充。」\n\n"
        + fork_slot_catalog_prompt()
        + "\n\n"
        + fork_slot_node_schema_hint()
    )
