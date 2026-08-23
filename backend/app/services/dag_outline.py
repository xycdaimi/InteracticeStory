from __future__ import annotations

import json
from typing import Any

from backend.app.models.enums import NodeKind
from backend.app.models.story_graph import StoryGraph
from backend.app.services.plot_paths import root_to_ending_path_count


def export_dag_outline(graph: StoryGraph) -> dict[str, Any]:
    """导出供合规 AI 分析的结构 DAG：节点标题/大纲 + 选项边，不含 script。"""
    nodes: list[dict[str, Any]] = []
    for nid, node in graph.nodes.items():
        row: dict[str, Any] = {
            "id": nid,
            "kind": node.kind.value,
            "title": (node.title or "").strip(),
            "summary": (node.summary or "").strip(),
        }
        if node.spine_event:
            row["spine_event"] = node.spine_event.strip()
        if node.kind == NodeKind.ending:
            if node.outcome:
                row["outcome"] = node.outcome
            if node.share_key:
                row["share_key"] = node.share_key
        nodes.append(row)

    choices: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for opt in graph.options:
        key = (opt.from_node_id, opt.to_node_id)
        if key in seen:
            continue
        seen.add(key)
        choices.append(
            {
                "from": opt.from_node_id,
                "to": opt.to_node_id,
                "label": (opt.label or "").strip(),
            }
        )

    return {
        "root_id": graph.root_id,
        "plot_line_count": root_to_ending_path_count(graph),
        "nodes": nodes,
        "choices": choices,
    }


def build_dag_compliance_prompt(
    *,
    outline: dict[str, Any],
    inspiration: str,
) -> str:
    return (
        "你是互动故事内容合规编辑。下面是一张剧情 DAG 的结构摘要"
        "（节点标题、大纲、选项台词；不含剧本正文细节）。\n"
        "请**只一轮**通读全图，找出涉现代政治、敏感涉政、违法违规、"
        "低俗有害等不宜上线之处。\n\n"
        "## 必须处理的红线（优先改写，不要删）\n"
        "- 涉现代政治：影射现实党政军、领导人、重大敏感事件\n"
        "- 涉恐极端、分裂颠覆、民族仇恨\n"
        "- 色情低俗、违法犯罪、未成年人不宜\n\n"
        "## 修复原则（非常重要）\n"
        "1. **默认用修改解决**：update_node（改 title/summary）、"
        "update_choice（改选项 label）、rewrite_script（改对白与状态，附完整 script）\n"
        "2. **禁止批量删除**。remove_branch 仅当某条分支经修改仍无法合规、"
        "且必须写明 cannot_fix_reason 时，才可删**一条** from→to 选项边\n"
        "3. remove_branch 只去掉该选项边，**不得**要求删除其他剧情线；"
        "共享节点与其他分支必须保留\n"
        "4. 拿不准时倾向 pass，仅明确违规才改\n"
        "5. 不要以结构问题（路径数、分叉层数）为由删分支\n\n"
        f"## 故事灵感\n{inspiration[:600]}\n\n"
        "## DAG 结构 JSON\n"
        f"{json.dumps(outline, ensure_ascii=False, indent=2)}\n\n"
        "若无问题，actions 可为空数组。"
    )
