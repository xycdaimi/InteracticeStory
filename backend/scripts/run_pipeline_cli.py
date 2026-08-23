from __future__ import annotations

import argparse
import asyncio

from backend.app.config import get_settings
from backend.app.graphs.fission_agent import run_fission
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path
from backend.app.services.produce_state import load_blueprint
from backend.app.services.story_repository import StoryRepository


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="全流程：裂变（LangGraph）→ 素材图 → 视频提示词"
    )
    parser.add_argument("--inspiration", required=True)
    parser.add_argument(
        "--fission-only",
        action="store_true",
        help="仅裂变，不跑素材与提示词",
    )
    args = parser.parse_args()
    get_settings.cache_clear()
    reset_engine_for_tests()
    await init_db()
    repo = StoryRepository()
    sid = await repo.create_story_indexed(args.inspiration)
    print(f"story_id={sid}")
    await run_fission(sid, include_produce=not args.fission_only)
    g = repo.load_graph(sid)
    meta = repo.load_meta(sid)
    print(
        f"phase={meta.phase} line_count={g.line_count} "
        f"endings={g.ending_count()} nodes={len(g.nodes)} "
        f"produce={meta.produce_status.value}"
    )
    if blueprint_path(sid).exists():
        bp = load_blueprint(sid)
        chars = bp.get("characters") or []
        nodes = bp.get("nodes") or []
        ready_prompts = sum(1 for n in nodes if n.get("shot_prompt_status") == "ready")
        print(
            f"blueprint: chars={len(chars)} nodes={len(nodes)} "
            f"prompts_ready={ready_prompts}"
        )


if __name__ == "__main__":
    asyncio.run(main())
