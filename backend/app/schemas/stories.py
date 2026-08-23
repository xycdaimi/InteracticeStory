from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.app.models.enums import FissionPhase, JobStatus, StoryStatus
from backend.app.models.events import ProgressEvent
from backend.app.models.story_graph import StoryGraph, StoryMeta


class CreateStoryIn(BaseModel):
    inspiration: str = Field(default="新故事", min_length=1)


class UpdateStoryIn(BaseModel):
    inspiration: str = Field(min_length=1)


class NodeLayoutIn(BaseModel):
    canvas_x: float
    canvas_y: float


class NodeLayoutOut(BaseModel):
    ok: bool = True
    node_id: str
    canvas_x: float
    canvas_y: float


class StoryListOut(BaseModel):
    stories: list[StoryMeta]


class CreateStoryOut(BaseModel):
    story_id: str
    status: StoryStatus
    phase: FissionPhase


class StartFissionOut(BaseModel):
    job_id: str
    status: JobStatus


class StoryDetailOut(BaseModel):
    meta: StoryMeta
    graph: StoryGraph


class EventsOut(BaseModel):
    events: list[ProgressEvent]
    next_since: int


class JobOut(BaseModel):
    job_id: str
    story_id: str
    type: str
    status: JobStatus
    error: str | None = None
    pause_reason: str | None = None


class StartAssetsOut(BaseModel):
    job_id: str
    status: JobStatus


class AssetsSummaryOut(BaseModel):
    story_id: str
    produce_status: str
    produce_paused_from: str | None = None
    produce_pause_reason: str | None = None
    characters: dict[str, int]
    scenes: dict[str, int]
    shot_prompts: dict[str, int]
    segments: dict[str, int]
    frames: dict[str, int] | None = None
    synthetic_frames: dict[str, int] | None = None
    chain_frames: dict[str, int] | None = None


class StartProduceOut(BaseModel):
    job_id: str
    status: JobStatus


class ProduceSummaryOut(AssetsSummaryOut):
    videos: dict[str, int]
    on_demand: dict[str, int] | None = None
    qc: dict[str, int]
    active_job: dict[str, str] | None = None


class BlueprintOut(BaseModel):
    blueprint: dict[str, Any]
