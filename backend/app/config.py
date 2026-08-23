from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("backend/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GeekAI
    geekai_api_key: str = ""
    geekai_base_url: str = "https://geekai.co/api/v1"
    chat_model: str = "gpt-5.4-mini"
    compliance_model: str = "gpt-5.4-mini"
    prompt_model: str = "gpt-5.4-mini"
    image_character_model: str = "gpt-image-2"
    image_scene_model: str = "nano-banana-2-lite"
    image_character_size: str = "1024x1024"
    image_scene_size: str = "1K"
    embedding_model: str = "text-embedding-3-small"

    # Exa
    exa_api_key: str = ""
    exa_base_url: str = "https://api.exa.ai"

    # ephone / MiniMax（视频出片，流程 §2）
    ephone_api_key: str = ""
    ephone_base_url: str = "https://api.ephone.ai"
    video_model: str = "MiniMax-H3"
    video_regen_model: str = "MiniMax-H3/regeneration"
    video_default_ratio: str = "16:9"
    video_resolution: str = "768P"

    # DashScope / Qwen Omni（视频质检，流程 §2）
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    video_qc_model: str = "qwen3-omni-flash"

    # Asset pipeline
    image_max_concurrency: int = 4
    prompt_max_concurrency: int = 8
    video_max_concurrency: int = 2
    video_poll_interval: float = 3.0
    prefetch_segment_ratio: float = 0.8
    data_dir: Path = Path("./data")
    # 最少剧情线数；新裂变流水线默认 8，可通过 MIN_STORY_LINES 覆盖（旧项目曾用 30）
    min_story_lines: int = 8
    # 裂变结构：单节点最大子分支数（每个分叉点最多几条出路，2–3 常见）
    fission_branch_depth: int = 3
    # 脉络：关键事件数（由 define_story_spine 定，非固定拍数）
    mainline_min_spine_events: int = 6
    mainline_max_spine_events: int = 70
    mainline_max_nodes: int = 80
    mainline_script_batch_size: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
