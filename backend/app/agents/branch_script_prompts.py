from __future__ import annotations

import json

from backend.app.models.fission_config import StoryStateTable

SYSTEM = """你是互动故事舞台剧本作者。必须通过 submit_scripts 工具提交剧本。
每个 script：duration_seconds=8；beats≥2 且含 t_start/t_end/shot/action/dialogue；
visual_plan.first_frame.depicts 必填；至少一句可听见对白。
dramatic_state_in 必须承接父节点 dramatic_state_out；开场须体现 option_label。
禁止只交大纲。"""


def build_branch_script_batch_prompt(
    *,
    batch_nodes: list[dict],
    story_state: StoryStateTable,
    parent_hints: dict[str, dict],
    completion_point: str,
) -> str:
    """batch_nodes: [{node_id, title, summary, option_label, tags, kind, outcome?}]"""
    return (
        f"故事完成点：{completion_point}\n"
        f"## StoryStateTable\n{story_state.model_dump_json(indent=2)}\n"
        f"## 父节点提示（dramatic_state_out / summary）\n"
        f"{json.dumps(parent_hints, ensure_ascii=False, indent=2)}\n"
        f"## 本批待写节点（按顺序为每个写完整 script）\n"
        f"{json.dumps(batch_nodes, ensure_ascii=False, indent=2)}\n"
        "要求：每个节点 script 可拍；ending 节点收束到其 outcome。"
    )
