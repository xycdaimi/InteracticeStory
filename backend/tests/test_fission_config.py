from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import get_settings
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import fission_config_path, story_state_path
from backend.app.models.fission_config import (
    CharacterConfig,
    EndingTargets,
    FissionConfig,
    StoryStateTable,
)
from backend.app.services.fission_config_store import (
    load_fission_config,
    load_story_state,
    save_fission_config,
    save_story_state,
)
from backend.app.services.story_repository import StoryRepository


@pytest.fixture()
def story_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_engine_for_tests()
    yield tmp_path
    get_settings.cache_clear()
    reset_engine_for_tests()


def test_fission_config_defaults() -> None:
    cfg = FissionConfig()
    assert cfg.branch_depth == 3
    assert cfg.branches_per_level == 3
    assert cfg.min_paths == 8
    assert cfg.ending_targets.completed == 1


def test_story_state_table_helpers() -> None:
    state = StoryStateTable()
    state = state.with_dramatic_state("对峙升级")
    state = state.add_fact("莉娜知道实验室秘密")
    state = state.add_fact("莉娜知道实验室秘密")
    assert state.dramatic_state == "对峙升级"
    assert state.story_facts == ["莉娜知道实验室秘密"]


def test_fission_config_round_trip(story_env: Path) -> None:
    sid = "test_story"
    cfg = FissionConfig(
        genre="悬疑",
        characters=[
            CharacterConfig(
                id="lina",
                name="莉娜",
                traits=["冷静"],
                state_keys=["信任", "怀疑"],
            )
        ],
        style_tags=["悬疑", "反转"],
        ending_targets=EndingTargets(near=4, failed=2, hidden=1),
        min_paths=10,
    )
    save_fission_config(sid, cfg)
    loaded = load_fission_config(sid)
    assert loaded is not None
    assert loaded.genre == "悬疑"
    assert loaded.characters[0].id == "lina"
    assert loaded.min_paths == 10
    assert fission_config_path(sid).exists()


def test_story_state_round_trip(story_env: Path) -> None:
    sid = "test_story"
    state = StoryStateTable(
        chapter=2,
        player_state={"trust_lina": 60, "has_key": True},
        story_facts=["地下室有脚印"],
        dramatic_state="紧张对峙",
    )
    save_story_state(sid, state)
    loaded = load_story_state(sid)
    assert loaded is not None
    assert loaded.player_state["trust_lina"] == 60
    assert loaded.story_facts == ["地下室有脚印"]
    assert story_state_path(sid).exists()


def test_fission_config_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FISSION_BRANCH_DEPTH", "4")
    monkeypatch.setenv("MIN_STORY_LINES", "12")
    get_settings.cache_clear()
    cfg = FissionConfig.from_settings("测试", get_settings())
    assert cfg.branch_depth == 4
    assert cfg.branches_per_level == 4
    assert cfg.min_paths == 12
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_repository_ensure_helpers(story_env: Path) -> None:
    await init_db()
    repo = StoryRepository()
    sid = await repo.create_story_indexed("实验室悬疑")
    cfg = repo.ensure_fission_config(sid)
    assert cfg.genre == "实验室悬疑"
    assert cfg.min_paths == get_settings().min_story_lines
    assert repo.load_fission_config(sid) is not None

    state = repo.ensure_story_state(sid)
    assert state.chapter == 1
    assert repo.load_story_state(sid) is not None

    same_cfg = repo.ensure_fission_config(sid)
    assert same_cfg.model_dump() == cfg.model_dump()
