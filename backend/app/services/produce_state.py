from __future__ import annotations

import json
from typing import Any

from backend.app.ai.errors import QuotaExhaustedError
from backend.app.infrastructure.paths import blueprint_path
from backend.app.models.enums import FissionPhase, JobStatus, ProduceStatus
from backend.app.services.story_repository import StoryRepository


def load_blueprint(story_id: str) -> dict[str, Any]:
    path = blueprint_path(story_id)
    if not path.exists():
        raise RuntimeError("缺少 blueprint.json，须先 persist_graph")
    return json.loads(path.read_text(encoding="utf-8"))


def save_blueprint(story_id: str, blueprint: dict[str, Any]) -> None:
    path = blueprint_path(story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_checkpoint(
    *,
    paused_from: ProduceStatus,
    blueprint: dict[str, Any],
    in_flight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    characters = blueprint.get("characters") or []
    scenes = blueprint.get("scenes") or []
    nodes = blueprint.get("nodes") or []
    return {
        "produce_paused_from": paused_from.value,
        "last_completed": {
            "cast_ids": [c["character_id"] for c in characters if c.get("status") == "ready"],
            "scene_ids": [s["scene_id"] for s in scenes if s.get("status") == "ready"],
            "prompt_node_ids": [
                n["node_id"]
                for n in nodes
                if n.get("shot_prompt_status") == "ready"
            ],
        },
        "in_flight": in_flight,
    }


async def pause_produce(
    repo: StoryRepository,
    *,
    story_id: str,
    job_id: str,
    paused_from: ProduceStatus,
    exc: QuotaExhaustedError,
    blueprint: dict[str, Any],
    in_flight: dict[str, Any] | None = None,
) -> None:
    checkpoint = build_checkpoint(
        paused_from=paused_from,
        blueprint=blueprint,
        in_flight=in_flight,
    )
    reason = f"quota:{exc.provider}:{exc.model}"
    meta = repo.load_meta(story_id)
    meta.produce_status = ProduceStatus.paused
    meta.produce_paused_from = paused_from.value
    meta.produce_pause_reason = exc.raw_message or reason
    blueprint["produce_status"] = ProduceStatus.paused.value
    save_blueprint(story_id, blueprint)
    repo.save_meta(meta)
    await repo.update_job(
        job_id,
        status=JobStatus.paused,
        error=reason,
        pause_reason=reason,
        checkpoint_json=json.dumps(checkpoint, ensure_ascii=False),
    )
    await repo.sync_story_row(story_id)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="paused",
        message=f"生产已暂停：{reason}",
        payload={"checkpoint": checkpoint, "reason": reason},
    )


def enter_awaiting_video(
    repo: StoryRepository,
    story_id: str,
    blueprint: dict[str, Any],
) -> None:
    set_produce_status(repo, story_id, blueprint, ProduceStatus.awaiting_video)
    repo.append_event(
        story_id,
        phase=FissionPhase.done,
        type="phase",
        message="人物/场景/提示词/首帧已完成，等待生成视频",
        payload={"stage": "awaiting_video"},
    )


def set_produce_status(
    repo: StoryRepository,
    story_id: str,
    blueprint: dict[str, Any],
    status: ProduceStatus,
) -> None:
    meta = repo.load_meta(story_id)
    meta.produce_status = status
    meta.produce_paused_from = None
    meta.produce_pause_reason = None
    blueprint["produce_status"] = status.value
    save_blueprint(story_id, blueprint)
    repo.save_meta(meta)
