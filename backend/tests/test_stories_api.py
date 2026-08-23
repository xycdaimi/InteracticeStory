from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.config import get_settings
from backend.app.infrastructure.db import init_db, reset_engine_for_tests
from backend.app.main import app


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
async def test_list_and_delete_story(client: AsyncClient):
    r = await client.post("/api/v1/stories", json={"inspiration": "列表测试故事"})
    assert r.status_code == 200
    sid = r.json()["story_id"]

    lst = await client.get("/api/v1/stories")
    assert lst.status_code == 200
    ids = [s["story_id"] for s in lst.json()["stories"]]
    assert sid in ids

    d = await client.delete(f"/api/v1/stories/{sid}")
    assert d.status_code == 200

    lst2 = await client.get("/api/v1/stories")
    ids2 = [s["story_id"] for s in lst2.json()["stories"]]
    assert sid not in ids2


@pytest.mark.asyncio
async def test_update_story_inspiration(client: AsyncClient):
    r = await client.post("/api/v1/stories", json={"inspiration": "旧灵感"})
    sid = r.json()["story_id"]
    u = await client.patch(f"/api/v1/stories/{sid}", json={"inspiration": "新灵感内容"})
    assert u.status_code == 200
    assert u.json()["meta"]["inspiration"] == "新灵感内容"


@pytest.mark.asyncio
async def test_create_story_and_get(client: AsyncClient):
    r = await client.post("/api/v1/stories", json={"inspiration": "讲一个关于桃园三结义的故事"})
    assert r.status_code == 200
    data = r.json()
    sid = data["story_id"]
    g = await client.get(f"/api/v1/stories/{sid}")
    assert g.status_code == 200
    body = g.json()
    assert body["meta"]["inspiration"].startswith("讲一个")
    assert "n_root" in body["graph"]["nodes"]
