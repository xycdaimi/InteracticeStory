from __future__ import annotations

import json
from typing import Any

from backend.app.infrastructure.paths import plot_tree_path
from backend.app.models.plot_tree import PlotTreeOutline


def load_plot_tree(story_id: str) -> PlotTreeOutline | None:
    path = plot_tree_path(story_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PlotTreeOutline.model_validate(data)


def save_plot_tree(story_id: str, outline: PlotTreeOutline | dict[str, Any]) -> None:
    if isinstance(outline, PlotTreeOutline):
        payload = outline.model_dump(by_alias=True)
    else:
        payload = PlotTreeOutline.model_validate(outline).model_dump(by_alias=True)
    path = plot_tree_path(story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
