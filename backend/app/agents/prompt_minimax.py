from __future__ import annotations

SYSTEM = """你是互动短剧分镜润色员。输入已是完整时码剧本与参考图绑定。

硬规则：
1. 只允许润色镜头用语、补视觉质感形容词。
2. 禁止增删情节、台词、参考角色；禁止改写【参考图】绑定段中的角色集合。
3. 输出严格 JSON，不要 markdown：
   {"prompt_text": "...", "duration_seconds": 8}
4. prompt_text 必须保留时码行（第a~bs）与原有对白原文。
5. duration_seconds：整数 4–15，优先沿用给定时长。"""


def build_shot_user(
    *,
    assembled_draft: str,
    duration_seconds: int,
    inspiration: str = "",
    continues_from_prev_shot: bool = False,
) -> str:
    continuity = (
        "镜头：连续承接上段末帧"
        if continues_from_prev_shot
        else "镜头：本镜可硬切或新建立"
    )
    return (
        f"故事灵感（仅背景，勿新增剧情）：{inspiration}\n"
        f"{continuity}\n"
        f"建议时长：{duration_seconds}\n"
        f"待润色初稿：\n{assembled_draft}\n"
        "请输出润色后的 JSON；保留全部原台词与【参考图】角色集合。"
    )


def ensure_lines_preserved(draft: str, polished: str) -> bool:
    """粗检：初稿中的对白『…』应仍出现在润色结果中。"""
    import re

    quotes = re.findall(r"[「『]([^」』]+)[」』]", draft)
    return all(q in polished for q in quotes)
