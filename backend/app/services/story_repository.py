from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from backend.app.config import get_settings
from backend.app.infrastructure.db import get_session_factory
from backend.app.infrastructure.orm import (
    CharacterRow,
    JobRow,
    SceneRow,
    ShotPromptRow,
    StoryEdgeRow,
    StoryEndingRow,
    StoryNodeRow,
    StoryOptionRow,
    StoryPlotLineRow,
    StoryRow,
    StorySegmentRow,
)
from backend.app.infrastructure.paths import (
    context_path,
    events_path,
    graph_path,
    meta_path,
    stories_root,
    story_dir,
)
from backend.app.models.fission_config import FissionConfig, StoryStateTable
from backend.app.services.fission_config_store import (
    load_fission_config,
    load_story_state,
    save_fission_config,
    save_story_state,
)
from backend.app.models.enums import FissionPhase, JobStatus, JobType, NodeKind, StoryStatus
from backend.app.models.events import ProgressEvent
from backend.app.models.job import JobRecord
from backend.app.models.story_graph import StoryGraph, StoryMeta, StoryNode


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class StoryRepository:
    def create_story(self, inspiration: str) -> str:
        story_id = uuid4().hex
        now = _now_iso()
        root = StoryNode(
            id="n_root",
            kind=NodeKind.root,
            title="起盘",
            summary=inspiration[:200],
            parent_id=None,
            canvas_x=0,
            canvas_y=0,
        )
        graph = StoryGraph(
            story_id=story_id,
            nodes={"n_root": root},
            edges=[],
            options=[],
            root_id="n_root",
        )
        meta = StoryMeta(
            story_id=story_id,
            inspiration=inspiration,
            status=StoryStatus.planning,
            phase=FissionPhase.idle,
            line_count=graph.line_count,
            ending_count=0,
            event_seq=0,
            created_at=now,
            updated_at=now,
        )
        d = story_dir(story_id)
        d.mkdir(parents=True, exist_ok=True)
        self.save_meta(meta)
        self.save_graph(graph)
        context_path(story_id).write_text("", encoding="utf-8")
        events_path(story_id).write_text("", encoding="utf-8")
        return story_id

    async def create_story_indexed(self, inspiration: str) -> str:
        story_id = self.create_story(inspiration)
        meta = self.load_meta(story_id)
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                StoryRow(
                    story_id=story_id,
                    inspiration=inspiration,
                    status=meta.status.value,
                    phase=meta.phase.value,
                    line_count=meta.line_count,
                    ending_count=meta.ending_count,
                )
            )
            await session.commit()
        return story_id

    def list_stories(self) -> list[StoryMeta]:
        root = stories_root()
        if not root.exists():
            return []
        metas: list[StoryMeta] = []
        for d in root.iterdir():
            if not d.is_dir() or not meta_path(d.name).exists():
                continue
            metas.append(self.load_meta(d.name))
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        return metas

    def update_inspiration(self, story_id: str, inspiration: str) -> StoryMeta:
        meta = self.load_meta(story_id)
        if meta.phase not in (FissionPhase.idle,):
            raise ValueError("only idle stories can update inspiration")
        meta.inspiration = inspiration.strip()
        graph = self.load_graph(story_id)
        root = graph.nodes.get(graph.root_id)
        if root is not None:
            root.summary = meta.inspiration[:200]
        self.save_graph(graph)
        self.save_meta(meta)
        return meta

    async def delete_story_indexed(self, story_id: str) -> None:
        for model in (
            StorySegmentRow,
            ShotPromptRow,
            SceneRow,
            CharacterRow,
            StoryEndingRow,
            StoryPlotLineRow,
            StoryOptionRow,
            StoryEdgeRow,
            StoryNodeRow,
            JobRow,
            StoryRow,
        ):
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(delete(model).where(model.story_id == story_id))
                await session.commit()
        d = story_dir(story_id)
        if d.exists():
            shutil.rmtree(d)

    def save_meta(self, meta: StoryMeta) -> None:
        meta.updated_at = _now_iso()
        _atomic_write(meta_path(meta.story_id), meta.model_dump_json(indent=2))

    def load_meta(self, story_id: str) -> StoryMeta:
        return StoryMeta.model_validate_json(meta_path(story_id).read_text(encoding="utf-8"))

    def update_node_layout(
        self, story_id: str, node_id: str, canvas_x: float, canvas_y: float
    ) -> StoryNode:
        graph = self.load_graph(story_id)
        node = graph.nodes.get(node_id)
        if node is None:
            raise KeyError(node_id)
        node.canvas_x = float(canvas_x)
        node.canvas_y = float(canvas_y)
        self.save_graph(graph)
        return node

    def save_graph(self, graph: StoryGraph) -> None:
        _atomic_write(graph_path(graph.story_id), graph.model_dump_json(indent=2))
        meta = self.load_meta(graph.story_id)
        meta.line_count = graph.line_count
        meta.ending_count = graph.ending_count()
        self.save_meta(meta)

    def load_graph(self, story_id: str) -> StoryGraph:
        return StoryGraph.model_validate_json(graph_path(story_id).read_text(encoding="utf-8"))

    def append_context(self, story_id: str, text: str) -> None:
        path = context_path(story_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n\n")

    def read_context(self, story_id: str) -> str:
        path = context_path(story_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def load_fission_config(self, story_id: str) -> FissionConfig | None:
        return load_fission_config(story_id)

    def save_fission_config(self, story_id: str, config: FissionConfig) -> None:
        save_fission_config(story_id, config)

    def load_story_state(self, story_id: str) -> StoryStateTable | None:
        return load_story_state(story_id)

    def save_story_state(self, story_id: str, state: StoryStateTable) -> None:
        save_story_state(story_id, state)

    def ensure_fission_config(
        self, story_id: str, *, inspiration: str | None = None
    ) -> FissionConfig:
        existing = self.load_fission_config(story_id)
        if existing is not None:
            return existing
        meta = self.load_meta(story_id)
        text = inspiration if inspiration is not None else meta.inspiration
        config = FissionConfig.from_settings(text, get_settings())
        self.save_fission_config(story_id, config)
        return config

    def ensure_story_state(self, story_id: str) -> StoryStateTable:
        existing = self.load_story_state(story_id)
        if existing is not None:
            return existing
        state = StoryStateTable()
        self.save_story_state(story_id, state)
        return state

    def append_event(
        self,
        story_id: str,
        *,
        phase: FissionPhase,
        type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> ProgressEvent:
        meta = self.load_meta(story_id)
        meta.event_seq += 1
        meta.phase = phase
        event = ProgressEvent(
            seq=meta.event_seq,
            ts=_now_iso(),
            phase=phase,
            type=type,
            message=message,
            payload=payload or {},
        )
        path = events_path(story_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        self.save_meta(meta)
        return event

    def list_events(self, story_id: str, since: int = 0) -> list[ProgressEvent]:
        path = events_path(story_id)
        if not path.exists():
            return []
        events: list[ProgressEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ev = ProgressEvent.model_validate_json(line)
            if ev.seq > since:
                events.append(ev)
        return events

    async def sync_story_row(self, story_id: str) -> None:
        meta = self.load_meta(story_id)
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(StoryRow, story_id)
            if row is None:
                session.add(
                    StoryRow(
                        story_id=story_id,
                        inspiration=meta.inspiration,
                        status=meta.status.value,
                        phase=meta.phase.value,
                        line_count=meta.line_count,
                        ending_count=meta.ending_count,
                        produce_status=meta.produce_status.value,
                    )
                )
            else:
                row.status = meta.status.value
                row.phase = meta.phase.value
                row.line_count = meta.line_count
                row.ending_count = meta.ending_count
                row.produce_status = meta.produce_status.value
            await session.commit()

    async def create_job(self, story_id: str, job_type: JobType = JobType.fission) -> JobRecord:
        now = _now_iso()
        job = JobRecord(
            job_id=uuid4().hex,
            story_id=story_id,
            type=job_type,
            status=JobStatus.pending,
            created_at=now,
            updated_at=now,
        )
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                JobRow(
                    job_id=job.job_id,
                    story_id=job.story_id,
                    type=job.type.value,
                    status=job.status.value,
                )
            )
            await session.commit()
        return job

    async def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        error: str | None = None,
        checkpoint_json: str | None = None,
        pause_reason: str | None = None,
    ) -> JobRecord | None:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(JobRow, job_id)
            if row is None:
                return None
            row.status = status.value
            if error is not None:
                row.error = error
            if checkpoint_json is not None:
                row.checkpoint_json = checkpoint_json
            if pause_reason is not None:
                row.pause_reason = pause_reason
            await session.commit()
            return self._job_from_row(row)

    def _job_from_row(self, row: JobRow) -> JobRecord:
        return JobRecord(
            job_id=row.job_id,
            story_id=row.story_id,
            type=JobType(row.type),
            status=JobStatus(row.status),
            error=row.error,
            checkpoint_json=row.checkpoint_json,
            pause_reason=row.pause_reason,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )

    async def get_job(self, job_id: str) -> JobRecord | None:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(JobRow, job_id)
            if row is None:
                return None
            return self._job_from_row(row)

    async def find_running_job(
        self, story_id: str, job_type: JobType
    ) -> JobRecord | None:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(JobRow).where(
                    JobRow.story_id == story_id,
                    JobRow.type == job_type.value,
                    JobRow.status.in_(
                        [JobStatus.pending.value, JobStatus.running.value]
                    ),
                )
            )
            row = result.scalars().first()
            if row is None:
                return None
            return self._job_from_row(row)

    async def find_running_fission(self, story_id: str) -> JobRecord | None:
        return await self.find_running_job(story_id, JobType.fission)


def ensure_stories_root() -> None:
    stories_root().mkdir(parents=True, exist_ok=True)
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
