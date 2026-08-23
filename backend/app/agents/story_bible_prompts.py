from __future__ import annotations

from backend.app.models.fission_config import FissionConfig

SYSTEM = """你是互动故事总编。根据灵感与控制参数，输出故事总纲 JSON（不要 markdown）。
只输出合法 JSON 对象，禁止写节点剧本 script。"""


def build_story_bible_prompt(*, inspiration: str, config: FissionConfig) -> str:
    min_e = 6
    max_e = 15
    et = config.ending_targets
    chars_hint = ""
    if config.characters:
        chars_hint = "优先使用配置中的角色：\n" + "\n".join(
            f"- {c.id}/{c.name} traits={c.traits} state_keys={c.state_keys}"
            for c in config.characters
        )
    return (
        "整理互动故事总纲。输出 JSON：\n"
        "{\n"
        '  "worldview": "世界观一句话",\n'
        '  "protagonist": "主角名与身份",\n'
        '  "characters": [{"id":"lina","name":"莉娜","traits":["冷静"],'
        '"state_keys":["信任","怀疑"]}],\n'
        '  "core_conflict": "核心冲突",\n'
        '  "ending_directions": ["HE方向","NE方向","BE方向"],\n'
        '  "key_events": ["按时间顺序的关键事件，最后一项抵达完成点"],\n'
        '  "completion_point": "故事完成点"\n'
        "}\n"
        f"key_events 数量 {min_e}–{max_e}；末项必须抵达 completion_point。\n"
        f"结局方向数量建议覆盖 completed≈{et.completed} near≈{et.near} "
        f"failed≈{et.failed}。\n"
        f"题材/风格：genre={config.genre!r} style_tags={config.style_tags}\n"
        f"{chars_hint}\n"
        f"## 灵感\n{inspiration}"
    )
