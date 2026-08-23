from __future__ import annotations

from typing import Any, Literal

from backend.app.models.plot_tree import PlotTreeOutline

ForkSlot = Literal["method", "stance", "info", "risk"]

FORK_SLOTS: dict[ForkSlot, dict[str, Any]] = {
    "method": {
        "label": "方式分叉",
        "question": "同一目标，玩家用什么做法推进？",
        "examples": [
            "直接问",
            "偷听",
            "诱导",
            "威胁",
            "绕路",
            "正面闯入",
        ],
    },
    "stance": {
        "label": "立场分叉",
        "question": "对关键人物/势力，玩家持什么态度？",
        "examples": [
            "相信对方",
            "怀疑对方",
            "暂时合作",
            "公开对抗",
            "保持距离观望",
        ],
    },
    "info": {
        "label": "信息分叉",
        "question": "玩家先拿到哪类信息、如何处理？",
        "examples": [
            "真相碎片",
            "误导线索",
            "延迟线索",
            "关键证据",
            "先藏后查",
        ],
    },
    "risk": {
        "label": "风险分叉",
        "question": "愿意付出什么代价、冒多大险？",
        "examples": [
            "安全推进",
            "高风险快进",
            "失去资源",
            "触发隐藏事件",
            "保全同伴",
        ],
    },
}

_SLOT_ORDER: list[ForkSlot] = ["method", "stance", "info", "risk"]


def fork_slot_catalog_prompt() -> str:
    lines = [
        "## 分叉维度库（填槽原料，禁止只写一条「最合理」动作）\n"
        "每个非 ending 节点是**分叉容器**，不是单场景推进点。"
        "不要问「要不要分叉」，而是为下列维度**逐槽填空**。\n"
    ]
    for key in _SLOT_ORDER:
        spec = FORK_SLOTS[key]
        ex = "、".join(spec["examples"][:5])
        lines.append(
            f"- **{key}**（{spec['label']}）：{spec['question']}\n"
            f"  例：{ex}"
        )
    lines.append(
        "\n每个非 ending 节点须从上述 4 维中**至少选 2 个不同维度**各填 1 条出路"
        f"（共 ≥2 条选择出边，≤ branch_depth）。"
        "子节点用 fork_slot 标明所属维度：method|stance|info|risk。\n"
        "禁止把「顺滑单链」当好故事；选项是结构硬要求，不是节奏建议。"
    )
    return "\n".join(lines)


def fork_slot_node_schema_hint() -> str:
    return (
        "节点示例（注意 fork_slot 与分叉容器 summary）：\n"
        '{"id":"S02","type":"branch","title":"巷口对峙",'
        '"summary":"对峙点：可选打听/试探/硬闯三条行动线",'
        '"parent":"S01","fork_slot":"method","option_label":"「偷听」"}\n'
        '{"id":"S02B","type":"branch","title":"巷口对峙",'
        '"summary":"同一对峙点：选择相信引路人",'
        '"parent":"S01","fork_slot":"stance","option_label":"「跟他走」"}\n'
    )


def _slots_for_node_title(title: str, summary: str) -> list[ForkSlot]:
    """按节点语义粗分配推荐槽位（修复时给模型填空提示）。"""
    text = f"{title} {summary}"
    picks: list[ForkSlot] = []
    if any(k in text for k in ("问", "偷", "闯", "绕", "追", "挡", "躲", "冲")):
        picks.append("method")
    if any(k in text for k in ("信", "疑", "合作", "对抗", "帮", "背叛")):
        picks.append("stance")
    if any(k in text for k in ("线索", "证据", "情报", "真相", "听说", "发现")):
        picks.append("info")
    if any(k in text for k in ("险", "伤", "赌", "暴露", "代价", "偷听", "硬")):
        picks.append("risk")
    for slot in _SLOT_ORDER:
        if slot not in picks:
            picks.append(slot)
    return picks[:3]


def build_slot_fill_plan(
    single_choice_nodes: list[dict[str, Any]],
) -> str:
    """为单选项节点生成「须填哪些槽」的清单。"""
    if not single_choice_nodes:
        return "无单选项节点。"
    lines: list[str] = []
    for item in single_choice_nodes[:12]:
        nid = item["id"]
        title = item.get("title") or ""
        summary = item.get("summary") or ""
        kids = item.get("children") or []
        slots = _slots_for_node_title(title, summary)
        slot_a, slot_b = slots[0], slots[1]
        spec_a = FORK_SLOTS[slot_a]
        spec_b = FORK_SLOTS[slot_b]
        existing = ""
        if len(kids) == 1:
            c = kids[0]
            existing = (
                f"已有唯一出路 → {c['id']}「{c['title']}」"
                f"（{c['type']}），须再填至少 1 个**不同维度**槽位。"
            )
        else:
            existing = "当前无子节点，须填 ≥2 个不同维度槽位。"
        lines.append(
            f"### {nid}「{title}」\n"
            f"- 现状：{existing}\n"
            f"- **必填空槽 1** — {slot_a}（{spec_a['label']}）：{spec_a['question']}\n"
            f"  参考：{'、'.join(spec_a['examples'][:4])}\n"
            f"- **必填空槽 2** — {slot_b}（{spec_b['label']}）：{spec_b['question']}\n"
            f"  参考：{'、'.join(spec_b['examples'][:4])}\n"
            f"- 改写 summary 为「分叉容器」表述（写出可选维度），勿写成单动作推进。"
        )
    return "\n".join(lines)


def build_slot_batch_repair_prompt(
    *,
    outline: PlotTreeOutline,
    single_choice_nodes: list[dict[str, Any]],
    errors: list[str],
    config_min_paths: int,
    path_count: int,
) -> str:
    """针对单选项节点的槽位填空修复（小批次，强制结构）。"""
    plan = build_slot_fill_plan(single_choice_nodes)
    return (
        "以下节点违反**硬结构**：非 ending 节点选择出边 < 2。"
        "禁止继续写单链。请按「填槽」而非「扩写分支」修订整棵 PlotTreeOutline JSON。\n\n"
        "## 工作流程（每个单选项节点必须执行）\n"
        "1. 把节点 summary 改成「分叉容器」（列出本节点可从哪几个维度选）\n"
        "2. 从 method/stance/info/risk 中选 ≥2 个不同维度\n"
        "3. 每个维度填 1 条出路（新子节点或汇合到已有节点），子节点标 fork_slot\n"
        "4. 选项 label 用「」写具体台词或可拍行动，禁止抽象词\n"
        "5. 已有唯一子节点可保留，但必须再补**不同 fork_slot** 的平行出路\n\n"
        + fork_slot_catalog_prompt()
        + "\n\n## 本批须填槽节点\n"
        + plan
        + "\n\n## 其他校验错误\n"
        + "\n".join(f"- {e}" for e in errors[:10])
        + f"\n\n## 路径数 {path_count} / 目标 {config_min_paths}\n"
        "输出完整 JSON；尽量复用已有 id；禁止 AUTO/占位结局糊弄。"
    )


def child_fork_slots(outline: PlotTreeOutline, parent_id: str) -> set[ForkSlot]:
    slots: set[ForkSlot] = set()
    for n in outline.nodes:
        if n.parent == parent_id and n.fork_slot:
            slots.add(n.fork_slot)
    for e in outline.edges:
        if e.from_id != parent_id:
            continue
        child = next((x for x in outline.nodes if x.id == e.to_id), None)
        if child and child.fork_slot:
            slots.add(child.fork_slot)
    return slots
