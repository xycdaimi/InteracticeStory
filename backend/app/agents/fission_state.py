from __future__ import annotations

from typing import Any, TypedDict

from backend.app.models.enums import FissionPhase


class FissionState(TypedDict, total=False):
    story_id: str
    messages: list[dict[str, Any]]
    phase: str
    line_count: int
    done: bool
    error: str
