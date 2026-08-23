from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from backend.app.models.enums import (
    ComplianceStatus,
    FissionPhase,
    NodeKind,
    ProduceStatus,
    StoryStatus,
)


class DialogueLine(BaseModel):
    speaker: str
    line: str


class ScriptBeat(BaseModel):
    t_start: float
    t_end: float
    shot: str = ""
    action: str = ""
    dialogue: list[DialogueLine] = Field(default_factory=list)
    pov: str | None = None

    @model_validator(mode="after")
    def _timing(self) -> ScriptBeat:
        if self.t_end <= self.t_start:
            raise ValueError("t_end must be greater than t_start")
        return self


class FirstFramePlan(BaseModel):
    required: bool = True
    depicts: str
    covers_character_ids: list[str] = Field(default_factory=list)


class CharacterRefNeed(BaseModel):
    character_id: str
    reason: str = "face_needed_not_in_first_frame"


class VisualPlan(BaseModel):
    first_frame: FirstFramePlan
    character_refs: list[CharacterRefNeed] = Field(default_factory=list)
    scene_ref: str | None = None
    hidden_or_pov_only_ids: list[str] = Field(default_factory=list)


class NodeScript(BaseModel):
    duration_seconds: int = Field(ge=4, le=15)
    dramatic_state_in: str
    dramatic_state_out: str
    beats: list[ScriptBeat] = Field(min_length=2)
    visual_plan: VisualPlan

    @model_validator(mode="after")
    def _validate_script(self) -> NodeScript:
        return repair_visual_plan(self)


def repair_visual_plan(script: NodeScript) -> NodeScript:
    """自动修正 visual_plan 常见冲突，再执行硬校验。"""
    vp = script.visual_plan
    covered = {c for c in vp.first_frame.covers_character_ids if c}
    hidden = {h for h in vp.hidden_or_pov_only_ids if h}
    refs = [
        r
        for r in vp.character_refs
        if r.character_id not in covered and r.character_id not in hidden
    ]
    if len(refs) != len(vp.character_refs):
        vp = vp.model_copy(update={"character_refs": refs})
        script = script.model_copy(update={"visual_plan": vp})
    validate_visual_plan(script)
    return script


def validate_visual_plan(script: NodeScript) -> None:
    vp = script.visual_plan
    covered = set(vp.first_frame.covers_character_ids)
    ref_ids = {r.character_id for r in vp.character_refs}
    hidden = set(vp.hidden_or_pov_only_ids)
    if covered & ref_ids:
        raise ValueError("covers_character_ids 与 character_refs 不得交集")
    if hidden & ref_ids:
        raise ValueError("hidden_or_pov_only 不得出现在 character_refs")
    if not any(b.dialogue for b in script.beats):
        raise ValueError("至少一句对白")


def summary_from_script(script: NodeScript, fallback: str = "") -> str:
    text = (script.dramatic_state_out or fallback or "").strip()
    return text[:80]


class StoryNode(BaseModel):
    id: str
    kind: NodeKind
    title: str
    summary: str = ""
    parent_id: str | None = None
    canvas_x: float = 0.0
    canvas_y: float = 0.0
    # persist 前可空；素材阶段只填图路径，不改名单
    character_ids: list[str] = Field(default_factory=list)
    scene_id: str | None = None
    # ending 节点在 converge 时写入
    share_key: str | None = None
    outcome: str | None = None
    script: NodeScript | None = None
    # 所属脉络关键事件（define_story_spine.key_events 中的一项）；多节点可共享同一事件
    spine_event: str | None = None


class StoryOption(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    label: str


class StoryEdge(BaseModel):
    id: str
    source: str
    target: str
    option_id: str | None = None


class PlotLine(BaseModel):
    """一条根→结局路径；合规审查的基本单位。"""

    line_id: str
    node_path: list[str]
    ending_id: str
    outcome: str | None = None
    share_key: str | None = None
    compliance_status: str = ComplianceStatus.pending.value
    reasons: list[str] = Field(default_factory=list)


class StoryGraph(BaseModel):
    story_id: str
    nodes: dict[str, StoryNode] = Field(default_factory=dict)
    edges: list[StoryEdge] = Field(default_factory=list)
    options: list[StoryOption] = Field(default_factory=list)
    root_id: str = "n_root"

    def leaf_ids(self) -> list[str]:
        sources = {e.source for e in self.edges}
        return [nid for nid in self.nodes if nid not in sources]

    def ending_inbound_count(self) -> int:
        """连入 ending 的边数 = 收束后的剧情线数（多线可共享同一结局节点）。"""
        ending_ids = {nid for nid, n in self.nodes.items() if n.kind == NodeKind.ending}
        if not ending_ids:
            return 0
        return sum(1 for e in self.edges if e.target in ending_ids)

    @property
    def line_count(self) -> int:
        """剧情线数 = root→ending 的不同有向完整路径条数。"""
        from backend.app.services.plot_paths import root_to_ending_path_count

        return root_to_ending_path_count(self)

    def ending_count(self) -> int:
        """唯一结局节点数（可共用同一视频片段的汇合点）。"""
        return sum(1 for n in self.nodes.values() if n.kind == NodeKind.ending)

    def open_plot_leaves(self) -> list[str]:
        """尚未收束为 ending 的叶节点 = 仍开放的剧情线尖端。"""
        return [nid for nid in self.leaf_ids() if self.nodes[nid].kind != NodeKind.ending]

    def can_converge(self, min_lines: int = 30) -> bool:
        from backend.app.services.plot_path_depth import can_converge_plot_lines

        return can_converge_plot_lines(self, min_lines)

    def iter_plot_lines(self) -> list[PlotLine]:
        """每条剧情线：root 起、ending 止的一条有向路径。"""
        from backend.app.services.plot_paths import enumerate_all_root_to_ending_paths

        paths = enumerate_all_root_to_ending_paths(self)
        lines: list[PlotLine] = []
        for i, path in enumerate(paths, start=1):
            ending_id = path[-1]
            ending = self.nodes[ending_id]
            lines.append(
                PlotLine(
                    line_id=f"pl_{i:04d}",
                    node_path=path,
                    ending_id=ending_id,
                    outcome=ending.outcome,
                    share_key=ending.share_key,
                    compliance_status=ComplianceStatus.pending.value,
                    reasons=[],
                )
            )
        return lines


class StoryMeta(BaseModel):
    story_id: str
    inspiration: str
    status: StoryStatus = StoryStatus.planning
    phase: FissionPhase = FissionPhase.idle
    line_count: int = 0
    ending_count: int = 0
    event_seq: int = 0
    produce_status: ProduceStatus = ProduceStatus.none
    produce_paused_from: str | None = None
    produce_pause_reason: str | None = None
    created_at: str
    updated_at: str
