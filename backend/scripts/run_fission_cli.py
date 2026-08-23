from __future__ import annotations

import argparse
import asyncio

from backend.app.config import get_settings
from backend.app.graphs.fission_agent import run_fission
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.services.story_repository import StoryRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run fission agent once")
    parser.add_argument("--inspiration", required=True)
    args = parser.parse_args()
    get_settings.cache_clear()
    reset_engine_for_tests()
    await init_db()
    repo = StoryRepository()
    sid = await repo.create_story_indexed(args.inspiration)
    print(f"story_id={sid}")
    await run_fission(sid)
    g = repo.load_graph(sid)
    meta = repo.load_meta(sid)
    print(f"phase={meta.phase} line_count={g.line_count} endings={g.ending_count()} nodes={len(g.nodes)}")


if __name__ == "__main__":
    asyncio.run(main())
