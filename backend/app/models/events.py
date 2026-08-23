from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.app.models.enums import FissionPhase


class ProgressEvent(BaseModel):
    seq: int
    ts: str
    phase: FissionPhase
    type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
