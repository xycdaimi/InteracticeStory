from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

PlotNodeType = Literal["start", "branch", "merge", "ending"]
PlotOutcome = Literal["completed", "near", "failed", "deferred"]
ForkSlot = Literal["method", "stance", "info", "risk"]


class PlotTreeNode(BaseModel):
    id: str = Field(min_length=1)
    type: PlotNodeType
    title: str = Field(min_length=1)
    summary: str = ""
    spine_event: str | None = None
    option_label: str = "继续"
    tags: list[str] = Field(default_factory=list)
    parent: str | None = None
    rejoin: str | None = None
    outcome: PlotOutcome | None = None
    share_key: str | None = None
    # 作为父节点某条选择出路时，标明分叉维度（填槽用，非 ending 子节点建议必填）
    fork_slot: ForkSlot | None = None


class PlotTreeEdge(BaseModel):
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    label: str = ""

    model_config = {"populate_by_name": True}


class PlotTreeOutline(BaseModel):
    """Pass2 纯结构剧情树：禁止含 script。"""

    root: str = Field(min_length=1)
    nodes: list[PlotTreeNode] = Field(min_length=2)
    edges: list[PlotTreeEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _basic(self) -> PlotTreeOutline:
        ids = {n.id for n in self.nodes}
        if self.root not in ids:
            raise ValueError(f"root {self.root!r} 不在 nodes 中")
        if len(ids) != len(self.nodes):
            raise ValueError("节点 id 重复")
        return self
