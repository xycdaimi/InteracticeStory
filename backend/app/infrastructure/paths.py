from __future__ import annotations

from pathlib import Path

from backend.app.config import get_settings


def data_root() -> Path:
    root = get_settings().data_dir
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def stories_root() -> Path:
    return data_root() / "stories"


def story_dir(story_id: str) -> Path:
    return stories_root() / story_id


def meta_path(story_id: str) -> Path:
    return story_dir(story_id) / "meta.json"


def graph_path(story_id: str) -> Path:
    return story_dir(story_id) / "graph.json"


def context_path(story_id: str) -> Path:
    return story_dir(story_id) / "context.md"


def spine_path(story_id: str) -> Path:
    return story_dir(story_id) / "spine.json"


def fission_config_path(story_id: str) -> Path:
    return story_dir(story_id) / "fission_config.json"


def story_state_path(story_id: str) -> Path:
    return story_dir(story_id) / "story_state.json"


def events_path(story_id: str) -> Path:
    return story_dir(story_id) / "events.jsonl"


def db_path() -> Path:
    return data_root() / "app.db"


def compliance_path(story_id: str) -> Path:
    return story_dir(story_id) / "compliance.json"


def blueprint_path(story_id: str) -> Path:
    return story_dir(story_id) / "blueprint.json"


def plot_tree_path(story_id: str) -> Path:
    return story_dir(story_id) / "plot_tree.json"


def assets_dir(story_id: str) -> Path:
    return story_dir(story_id) / "assets"


def character_image_path(story_id: str, character_id: str) -> Path:
    return assets_dir(story_id) / "characters" / f"{character_id}.png"


def scene_image_path(story_id: str, scene_id: str) -> Path:
    return assets_dir(story_id) / "scenes" / f"{scene_id}.png"


def shot_prompt_path(story_id: str, node_id: str) -> Path:
    return assets_dir(story_id) / "prompts" / f"{node_id}.json"


def segment_first_frame_path(story_id: str, segment_id: str) -> Path:
    return assets_dir(story_id) / "frames" / f"{segment_id}_first.png"


def segment_last_frame_path(story_id: str, segment_id: str) -> Path:
    return assets_dir(story_id) / "frames" / f"{segment_id}_last.png"


def segment_video_path(story_id: str, segment_id: str) -> Path:
    return assets_dir(story_id) / "videos" / f"{segment_id}.mp4"


def ensure_asset_dirs(story_id: str) -> Path:
    root = assets_dir(story_id)
    for sub in ("characters", "scenes", "prompts", "frames", "videos"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root

