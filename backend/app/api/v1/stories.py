from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.app.models.enums import JobStatus
from backend.app.schemas.stories import (
    AssetsSummaryOut,
    BlueprintOut,
    CreateStoryIn,
    CreateStoryOut,
    EventsOut,
    JobOut,
    NodeLayoutIn,
    NodeLayoutOut,
    ProduceSummaryOut,
    StartAssetsOut,
    StartFissionOut,
    StartProduceOut,
    StoryDetailOut,
    StoryListOut,
    UpdateStoryIn,
)
from backend.app.services.assets_service import AssetsService
from backend.app.services.produce_service import ProduceService
from backend.app.services.comfy_export import story_graph_to_comfy_workflow
from backend.app.services.fission_service import FissionService
from backend.app.infrastructure.paths import blueprint_path, story_dir
from backend.app.services.story_repository import StoryRepository

router = APIRouter(tags=["stories"])
_repo = StoryRepository()
_svc = FissionService(_repo)
_assets = AssetsService(_repo)
_produce = ProduceService(_repo)


@router.get("/stories", response_model=StoryListOut)
async def list_stories() -> StoryListOut:
    return StoryListOut(stories=_repo.list_stories())


@router.post("/stories", response_model=CreateStoryOut)
async def create_story(body: CreateStoryIn) -> CreateStoryOut:
    sid = await _svc.create_story(body.inspiration)
    meta = _repo.load_meta(sid)
    return CreateStoryOut(story_id=sid, status=meta.status, phase=meta.phase)


@router.patch("/stories/{story_id}", response_model=StoryDetailOut)
async def update_story(story_id: str, body: UpdateStoryIn) -> StoryDetailOut:
    try:
        meta = _repo.update_inspiration(story_id, body.inspiration)
        graph = _repo.load_graph(story_id)
        await _repo.sync_story_row(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return StoryDetailOut(meta=meta, graph=graph)


@router.delete("/stories/{story_id}")
async def delete_story(story_id: str) -> dict:
    try:
        _repo.load_meta(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    await _repo.delete_story_indexed(story_id)
    return {"ok": True}


@router.post("/stories/{story_id}/fission", response_model=StartFissionOut)
async def start_fission(story_id: str) -> StartFissionOut:
    job_id = await _svc.start_fission(story_id)
    return StartFissionOut(job_id=job_id, status=JobStatus.pending)


@router.get("/stories/{story_id}", response_model=StoryDetailOut)
async def get_story(story_id: str) -> StoryDetailOut:
    try:
        meta = _repo.load_meta(story_id)
        graph = _repo.load_graph(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    return StoryDetailOut(meta=meta, graph=graph)


@router.patch(
    "/stories/{story_id}/nodes/{node_id}/layout",
    response_model=NodeLayoutOut,
)
async def update_node_layout(
    story_id: str, node_id: str, body: NodeLayoutIn
) -> NodeLayoutOut:
    try:
        _repo.load_meta(story_id)
        node = _repo.update_node_layout(
            story_id, node_id, body.canvas_x, body.canvas_y
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail="node not found") from e
    return NodeLayoutOut(
        ok=True,
        node_id=node.id,
        canvas_x=node.canvas_x,
        canvas_y=node.canvas_y,
    )


@router.get("/stories/{story_id}/events", response_model=EventsOut)
async def get_events(story_id: str, since: int = 0) -> EventsOut:
    try:
        _repo.load_meta(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    events = _repo.list_events(story_id, since=since)
    next_since = events[-1].seq if events else since
    return EventsOut(events=events, next_since=next_since)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str) -> JobOut:
    job = await _repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(
        job_id=job.job_id,
        story_id=job.story_id,
        type=job.type.value,
        status=job.status,
        error=job.error,
        pause_reason=job.pause_reason,
    )


@router.get("/stories/{story_id}/comfy-workflow")
async def get_comfy_workflow(story_id: str) -> dict:
    try:
        graph = _repo.load_graph(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    return story_graph_to_comfy_workflow(graph)

@router.get("/stories/{story_id}/production-blueprint", response_model=BlueprintOut)
async def get_production_blueprint(story_id: str) -> BlueprintOut:
    path = blueprint_path(story_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="blueprint not found")
    import json
    return BlueprintOut(blueprint=json.loads(path.read_text(encoding="utf-8")))


@router.get("/stories/{story_id}/media/{file_path:path}")
async def get_story_media(story_id: str, file_path: str) -> FileResponse:
    """提供故事目录下 assets/ 相对路径的媒体文件（定妆图、场景图、首帧等）。"""
    try:
        _repo.load_meta(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    normalized = file_path.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/") or not normalized.startswith("assets/"):
        raise HTTPException(status_code=400, detail="invalid media path")
    path = (story_dir(story_id) / normalized).resolve()
    root = story_dir(story_id).resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        raise HTTPException(status_code=404, detail="media not found")
    return FileResponse(path)


@router.post("/stories/{story_id}/assets/generate", response_model=StartAssetsOut)
async def start_assets_generate(story_id: str) -> StartAssetsOut:
    job_id = await _assets.start_assets(story_id)
    return StartAssetsOut(job_id=job_id, status=JobStatus.pending)


@router.post("/stories/{story_id}/assets/resume", response_model=StartAssetsOut)
async def resume_assets_generate(story_id: str) -> StartAssetsOut:
    job_id = await _assets.resume_assets(story_id)
    return StartAssetsOut(job_id=job_id, status=JobStatus.pending)


@router.get("/stories/{story_id}/assets", response_model=AssetsSummaryOut)
async def get_assets_status(story_id: str) -> AssetsSummaryOut:
    try:
        _repo.load_meta(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    if not blueprint_path(story_id).exists():
        raise HTTPException(status_code=404, detail="blueprint not found")
    summary = _assets.get_assets_summary(story_id)
    return AssetsSummaryOut(**summary)


@router.post("/stories/{story_id}/produce", response_model=StartProduceOut)
async def start_produce(story_id: str) -> StartProduceOut:
    job_id = await _produce.start_produce(story_id)
    return StartProduceOut(job_id=job_id, status=JobStatus.pending)


@router.post("/stories/{story_id}/produce/videos", response_model=StartProduceOut)
async def start_produce_videos(story_id: str) -> StartProduceOut:
    job_id = await _produce.start_video_produce(story_id)
    return StartProduceOut(job_id=job_id, status=JobStatus.pending)


@router.post("/stories/{story_id}/produce/resume", response_model=StartProduceOut)
async def resume_produce(story_id: str) -> StartProduceOut:
    job_id = await _produce.resume_produce(story_id)
    return StartProduceOut(job_id=job_id, status=JobStatus.pending)


@router.post("/stories/{story_id}/segments/{segment_id}/produce")
async def produce_segment_on_demand(story_id: str, segment_id: str) -> dict:
    """游玩时按需生成单个视频片段。"""
    from backend.app.services.runtime_produce import produce_segment_on_demand as _produce_segment

    try:
        _repo.load_meta(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    if not blueprint_path(story_id).exists():
        raise HTTPException(status_code=404, detail="blueprint not found")
    return await _produce_segment(story_id, segment_id, repo=_repo)


@router.get("/stories/{story_id}/produce", response_model=ProduceSummaryOut)
async def get_produce_status(story_id: str) -> ProduceSummaryOut:
    try:
        _repo.load_meta(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="story not found") from e
    if not blueprint_path(story_id).exists():
        raise HTTPException(status_code=404, detail="blueprint not found")
    return ProduceSummaryOut(**await _produce.get_produce_summary(story_id))

