from __future__ import annotations

import re

# 单独出现即视为无效
_VAGUE_EXACT = frozenset(
    {
        "意图",
        "行动",
        "动作",
        "选择",
        "选项",
        "决定",
        "继续",
        "观察",
        "试探",
        "回避",
        "靠近",
        "离开",
        "前进",
        "后退",
        "下一步",
        "主线推进",
        "抵达结局",
    }
)

_META_PREFIX = re.compile(r"^(选择|决定|采取|执行|进行)")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def validate_protagonist_choice_label(label: str) -> str | None:
    """
    玩家选项 = 主角此刻会说的具体话，或主角会做的具体行动（可拍）。
    返回错误说明；None 表示通过。
    """
    text = (label or "").strip()
    if len(text) < 4:
        return "选项过短：须写主角具体台词（带「」）或具体可拍行动"
    if text in _VAGUE_EXACT:
        return f"禁止抽象选项「{text}」：须写主角视角下的具体台词或具体行动"
    if _META_PREFIX.match(text) and len(text) < 12:
        return "选项像元描述而非主角抉择，请改成具体台词或具体行动"
    # 仅拦截极短的纯英文/数字笼统词；中文具体行动（≥4 字）放行
    if (
        not _has_cjk(text)
        and text == text.lower()
        and len(text) <= 8
        and "「" not in text
    ):
        return "选项过于笼统，请写主角会说的具体话或会做的具体事"
    return None
