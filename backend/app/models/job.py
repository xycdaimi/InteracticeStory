from __future__ import annotations

from pydantic import BaseModel

from backend.app.models.enums import JobStatus, JobType


class JobRecord(BaseModel):
    job_id: str
    story_id: str
    type: JobType = JobType.fission
    status: JobStatus = JobStatus.pending
    error: str | None = None
    checkpoint_json: str | None = None
    pause_reason: str | None = None
    created_at: str
    updated_at: str
