from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class StoryRow(Base):
    __tablename__ = "stories"

    story_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    inspiration: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="planning")
    phase: Mapped[str] = mapped_column(String(32), default="idle")
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    ending_count: Mapped[int] = mapped_column(Integer, default=0)
    produce_status: Mapped[str] = mapped_column(String(32), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class JobRow(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(32), default="fission")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StoryNodeRow(Base):
    __tablename__ = "story_nodes"
    __table_args__ = (UniqueConstraint("story_id", "node_id", name="uq_story_node"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32), default="main")
    title: Mapped[str] = mapped_column(String(256), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canvas_x: Mapped[float] = mapped_column(default=0.0)
    canvas_y: Mapped[float] = mapped_column(default=0.0)
    character_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    script_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class StoryEdgeRow(Base):
    __tablename__ = "story_edges"
    __table_args__ = (UniqueConstraint("story_id", "edge_id", name="uq_story_edge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    edge_id: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64))
    option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class StoryOptionRow(Base):
    __tablename__ = "story_options"
    __table_args__ = (UniqueConstraint("story_id", "option_id", name="uq_story_option"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    option_id: Mapped[str] = mapped_column(String(64))
    from_node_id: Mapped[str] = mapped_column(String(64))
    to_node_id: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(256), default="")


class StoryPlotLineRow(Base):
    __tablename__ = "story_plot_lines"
    __table_args__ = (UniqueConstraint("story_id", "line_id", name="uq_story_plot_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    line_id: Mapped[str] = mapped_column(String(64))
    node_path_json: Mapped[str] = mapped_column(Text, default="[]")
    ending_id: Mapped[str] = mapped_column(String(64), default="")
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compliance_status: Mapped[str] = mapped_column(String(32), default="pass")
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")


class StoryEndingRow(Base):
    __tablename__ = "story_endings"
    __table_args__ = (UniqueConstraint("story_id", "ending_id", name="uq_story_ending"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    ending_id: Mapped[str] = mapped_column(String(64))
    share_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(256), default="")


class CharacterRow(Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("story_id", "character_id", name="uq_character"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    character_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), default="")
    appearance_prompt: Mapped[str] = mapped_column(Text, default="")
    traits_json: Mapped[str] = mapped_column(Text, default="[]")
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")


class SceneRow(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("story_id", "scene_id", name="uq_scene"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    scene_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")


class ShotPromptRow(Base):
    __tablename__ = "shot_prompts"
    __table_args__ = (UniqueConstraint("story_id", "node_id", name="uq_shot_prompt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    character_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ref_image_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="pending")


class StorySegmentRow(Base):
    __tablename__ = "story_segments"
    __table_args__ = (UniqueConstraint("story_id", "segment_id", name="uq_story_segment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(String(64), index=True)
    segment_id: Mapped[str] = mapped_column(String(64))
    from_node_id: Mapped[str] = mapped_column(String(64))
    to_node_id: Mapped[str] = mapped_column(String(64))
    option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    continuity_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    continues_from_prev_shot: Mapped[bool] = mapped_column(default=False)
    continuity_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_frame_source: Mapped[str] = mapped_column(String(32), default="synthetic")
    pred_segment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_frame_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_frame_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_node_id: Mapped[str] = mapped_column(String(64), default="")
    shot_prompt_status: Mapped[str] = mapped_column(String(32), default="pending")
    video_status: Mapped[str] = mapped_column(String(32), default="pending")
    qc_status: Mapped[str] = mapped_column(String(32), default="pending")
    regen_count: Mapped[int] = mapped_column(Integer, default=0)
    ephone_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    qc_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
