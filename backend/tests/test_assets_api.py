from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.infrastructure.paths import blueprint_path, story_dir
from backend.app.main import app
from backend.app.services.story_repository import StoryRepository


@pytest.fixture
async def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_engine_for_tests()
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_assets_generate_requires_blueprint(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/v1/stories", json={"inspiration": "测试"})
    sid = r.json()["story_id"]
    r2 = await api_client.post(f"/api/v1/stories/{sid}/assets/generate")
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_get_story_media(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/v1/stories", json={"inspiration": "测试"})
    sid = r.json()["story_id"]
    assets = story_dir(sid) / "assets" / "characters" / "c1.png"
    assets.parent.mkdir(parents=True, exist_ok=True)
    assets.write_bytes(b"png")

    ok = await api_client.get(f"/api/v1/stories/{sid}/media/assets/characters/c1.png")
    assert ok.status_code == 200
    assert ok.content == b"png"

    bad = await api_client.get(f"/api/v1/stories/{sid}/media/meta.json")
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_get_assets_summary(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/v1/stories", json={"inspiration": "测试"})
    sid = r.json()["story_id"]
    blueprint = {
        "story_id": sid,
        "produce_status": "none",
        "characters": [{"character_id": "c1", "status": "pending"}],
        "scenes": [{"scene_id": "s1", "status": "ready"}],
        "nodes": [{"node_id": "n1", "shot_prompt_status": "pending"}],
        "segments": [{"segment_id": "seg1", "first_frame_source": "synthetic"}],
    }
    story_dir(sid).mkdir(parents=True, exist_ok=True)
    blueprint_path(sid).write_text(json.dumps(blueprint), encoding="utf-8")

    r2 = await api_client.get(f"/api/v1/stories/{sid}/assets")
    assert r2.status_code == 200
    data = r2.json()
    assert data["characters"]["total"] == 1
    assert data["scenes"]["ready"] == 1
    assert data["segments"]["total"] == 1
