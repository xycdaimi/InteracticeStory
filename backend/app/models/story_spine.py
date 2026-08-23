from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class StorySpine(BaseModel):
    """脉络主线蓝图：关键事件组成完整故事链路；每个事件可剧本化为多个可拍节点。"""

    protagonist: str = Field(min_length=1)
    completion_point: str = Field(
        min_length=4,
        description="故事完成点：主角达成什么、世界处于什么状态",
    )
    key_events: list[str] = Field(
        min_length=5,
        max_length=70,
        description="按时间顺序的关键事件；最后一项应抵达 completion_point",
    )

    @model_validator(mode="after")
    def _completion_in_arc(self) -> StorySpine:
        tail = (self.key_events[-1] if self.key_events else "").strip()
        cp = self.completion_point.strip()
        if cp and tail and cp[:8] not in tail and tail[:8] not in cp:
            # 软提示：末事件与完成点应呼应（写入时不硬失败，finalize 时再严检）
            pass
        return self
