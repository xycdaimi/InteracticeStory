from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from backend.app.ai.geekai_image import GeekAIImageClient
from backend.app.ai.errors import QuotaExhaustedError
from backend.app.config import Settings


@pytest.mark.asyncio
async def test_geekai_image_generations_writes_png(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n"
    settings = Settings(
        geekai_api_key="test-key",
        geekai_base_url="https://geekai.test/api/v1",
        image_character_model="gpt-image-2",
    )
    dest = tmp_path / "c.png"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = httpx.Request("POST", "http://x", json={}).read()
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(png_bytes).decode()}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=settings.geekai_base_url) as client:
        img = GeekAIImageClient(settings=settings, client=client)
        out = await img.generate_png(
            model="gpt-image-2",
            prompt="刘备肖像",
            dest=dest,
        )
        assert out == dest
        assert dest.read_bytes() == png_bytes


@pytest.mark.asyncio
async def test_geekai_image_quota_error(tmp_path: Path) -> None:
    settings = Settings(geekai_api_key="k", geekai_base_url="https://geekai.test/api/v1")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="insufficient balance")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=settings.geekai_base_url) as client:
        img = GeekAIImageClient(settings=settings, client=client)
        with pytest.raises(QuotaExhaustedError):
            await img.generate_png(
                model="gpt-image-2",
                prompt="x",
                dest=tmp_path / "x.png",
            )
