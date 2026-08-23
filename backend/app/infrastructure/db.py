from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.app.infrastructure.orm import Base
from backend.app.infrastructure.paths import data_root, db_path

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = f"sqlite+aiosqlite:///{db_path()}"
        _engine = create_async_engine(url, echo=False)
    return _engine


def reset_engine_for_tests() -> None:
    """Drop cached engine so tests can point DATA_DIR elsewhere."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


def _sqlite_add_missing_columns(connection) -> None:
    """开发期轻量迁移：create_all 不会给已有表加列。"""
    from sqlalchemy import text

    stories_cols = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(stories)")).fetchall()
    }
    if stories_cols and "produce_status" not in stories_cols:
        connection.execute(
            text(
                "ALTER TABLE stories ADD COLUMN produce_status VARCHAR(32) "
                "NOT NULL DEFAULT 'none'"
            )
        )

    jobs_cols = {
        row[1] for row in connection.execute(text("PRAGMA table_info(jobs)")).fetchall()
    }
    if jobs_cols:
        if "checkpoint_json" not in jobs_cols:
            connection.execute(
                text("ALTER TABLE jobs ADD COLUMN checkpoint_json TEXT")
            )
        if "pause_reason" not in jobs_cols:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN pause_reason TEXT"))

    seg_cols = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(story_segments)")).fetchall()
    }
    if seg_cols:
        if "regen_count" not in seg_cols:
            connection.execute(
                text(
                    "ALTER TABLE story_segments ADD COLUMN regen_count INTEGER "
                    "NOT NULL DEFAULT 0"
                )
            )
        if "ephone_task_id" not in seg_cols:
            connection.execute(text("ALTER TABLE story_segments ADD COLUMN ephone_task_id VARCHAR(128)"))
        if "qc_reasons_json" not in seg_cols:
            connection.execute(
                text("ALTER TABLE story_segments ADD COLUMN qc_reasons_json TEXT DEFAULT '[]'")
            )
        if "continues_from_prev_shot" not in seg_cols:
            connection.execute(
                text(
                    "ALTER TABLE story_segments ADD COLUMN continues_from_prev_shot "
                    "BOOLEAN DEFAULT 0"
                )
            )
        if "continuity_reason" not in seg_cols:
            connection.execute(
                text("ALTER TABLE story_segments ADD COLUMN continuity_reason TEXT")
            )

    node_cols = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info(story_nodes)")).fetchall()
    }
    if node_cols and "script_json" not in node_cols:
        connection.execute(text("ALTER TABLE story_nodes ADD COLUMN script_json TEXT"))


async def init_db() -> None:
    data_root().mkdir(parents=True, exist_ok=True)
    (data_root() / "stories").mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_missing_columns)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
