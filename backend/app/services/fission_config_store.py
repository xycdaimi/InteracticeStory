from __future__ import annotations

from backend.app.infrastructure.paths import fission_config_path, story_state_path
from backend.app.models.fission_config import FissionConfig, StoryStateTable


def _atomic_write_json(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_fission_config(story_id: str) -> FissionConfig | None:
    path = fission_config_path(story_id)
    if not path.exists():
        return None
    return FissionConfig.model_validate_json(path.read_text(encoding="utf-8"))


def save_fission_config(story_id: str, config: FissionConfig) -> None:
    _atomic_write_json(
        fission_config_path(story_id),
        config.model_dump_json(indent=2),
    )


def load_story_state(story_id: str) -> StoryStateTable | None:
    path = story_state_path(story_id)
    if not path.exists():
        return None
    return StoryStateTable.model_validate_json(path.read_text(encoding="utf-8"))


def save_story_state(story_id: str, state: StoryStateTable) -> None:
    _atomic_write_json(
        story_state_path(story_id),
        state.model_dump_json(indent=2),
    )
