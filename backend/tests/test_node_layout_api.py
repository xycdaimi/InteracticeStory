from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.config import get_settings
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.main import app
from backend.app.services.story_repository import StoryRepository


@pytest.fixture()
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MIN_STORY_LINES", "5")
    get_settings.cache_clear()
    reset_engine_for_tests()
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()
    reset_engine_for_tests()


@pytest.mark.asyncio
async def test_update_node_layout_persists(client: AsyncClient, tmp_path: Path):
    r = await client.post("/api/v1/stories", json={"inspiration": "layout test"})
    sid = r.json()["story_id"]

    resp = await client.patch(
        f"/api/v1/stories/{sid}/nodes/n_root/layout",
        json={"canvas_x": 120.5, "canvas_y": -40.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["canvas_x"] == 120.5
    assert data["canvas_y"] == -40.0

    g = StoryRepository().load_graph(sid)
    assert g.nodes["n_root"].canvas_x == 120.5
    assert g.nodes["n_root"].canvas_y == -40.0


@pytest.mark.asyncio
async def test_update_node_layout_404(client: AsyncClient):
    r = await client.post("/api/v1/stories", json={"inspiration": "layout miss"})
    sid = r.json()["story_id"]
    resp = await client.patch(
        f"/api/v1/stories/{sid}/nodes/no_such/layout",
        json={"canvas_x": 1, "canvas_y": 2},
    )
    assert resp.status_code == 404
