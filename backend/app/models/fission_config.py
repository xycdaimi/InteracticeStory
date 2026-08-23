from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class CharacterConfig(BaseModel):
    """裂变控制参数中的角色定义。"""

    id: str = Field(min_length=1, description="稳定标识，如 lina")
    name: str = Field(min_length=1)
    traits: list[str] = Field(default_factory=list)
    state_keys: list[str] = Field(
        default_factory=list,
        description="该角色可追踪的状态维度，如信任/好感/怀疑/立场",
    )


class EndingTargets(BaseModel):
    """结局数量目标。"""

    completed: int = Field(default=1, ge=0, le=3, description="Happy End，全剧通常 1 个")
    near: int = Field(default=4, ge=0, le=10, description="普通结局")
    failed: int = Field(default=3, ge=0, le=10, description="坏结局")
    hidden: int = Field(default=1, ge=0, le=5, description="隐藏结局")
    deferred: int = Field(default=0, ge=0, le=3, description="开放结局")


class FissionConfig(BaseModel):
    """裂变流水线统一控制参数；每个故事一份。"""

    genre: str = Field(default="", description="题材，如悬疑/恋爱")
    target_duration_minutes: int = Field(default=15, ge=5, le=180)
    branch_depth: int = Field(
        default=3,
        ge=2,
        le=5,
        description="单节点最大子分支数：每个分叉点最多几条玩家选择出路（2–3 常见）",
    )
    branches_per_level: int = Field(
        default=3,
        ge=2,
        le=5,
        description="（已废弃，与 branch_depth 同义；保留兼容旧配置）",
    )
    ending_targets: EndingTargets = Field(default_factory=EndingTargets)
    characters: list[CharacterConfig] = Field(default_factory=list)
    style_tags: list[str] = Field(
        default_factory=list,
        description="剧情标签：悬疑/恋爱/战斗/选择/反转/真相 等",
    )
    min_paths: int = Field(
        default=8,
        ge=2,
        le=100,
        description="最少完整剧情线数；跑通后可调高",
    )

    @model_validator(mode="after")
    def _normalize_tags(self) -> FissionConfig:
        self.style_tags = [t.strip() for t in self.style_tags if t.strip()]
        # 统一：branches_per_level 与 branch_depth 同义
        if self.branches_per_level != self.branch_depth:
            object.__setattr__(self, "branches_per_level", self.branch_depth)
        return self

    @classmethod
    def from_inspiration(
        cls,
        inspiration: str,
        *,
        min_paths: int = 8,
        branch_depth: int = 3,
        branches_per_level: int | None = None,
    ) -> FissionConfig:
        """从用户灵感创建默认配置。"""
        bd = branch_depth
        return cls(
            genre=inspiration[:40].strip(),
            min_paths=min_paths,
            branch_depth=bd,
            branches_per_level=branches_per_level if branches_per_level is not None else bd,
        )

    @classmethod
    def from_settings(cls, inspiration: str, settings: object) -> FissionConfig:
        """从全局 Settings 初始化（.env 默认值）。"""
        bd = int(getattr(settings, "fission_branch_depth", 3))
        return cls.from_inspiration(
            inspiration,
            min_paths=int(getattr(settings, "min_story_lines", 8)),
            branch_depth=bd,
        )


class StoryStateTable(BaseModel):
    """故事状态表：每次节点生成携带，保证「有记忆」。"""

    chapter: int = Field(default=1, ge=1)
    player_state: dict[str, int | bool | str] = Field(
        default_factory=dict,
        description="角色变量，如 trust_lina: 60, has_key: true",
    )
    story_facts: list[str] = Field(
        default_factory=list,
        description="已确立的剧情事实，供后续生成引用",
    )
    dramatic_state: str = Field(
        default="",
        description="当前戏剧状态摘要，通常承接上一节点 dramatic_state_out",
    )

    def with_dramatic_state(self, state: str) -> StoryStateTable:
        out = state.strip()
        if not out or out == self.dramatic_state:
            return self
        return self.model_copy(update={"dramatic_state": out})

    def add_fact(self, fact: str) -> StoryStateTable:
        text = fact.strip()
        if not text or text in self.story_facts:
            return self
        return self.model_copy(update={"story_facts": [*self.story_facts, text]})
