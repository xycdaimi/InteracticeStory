from __future__ import annotations

import httpx
import pytest

from backend.app.ai.exa_client import ExaClient
from backend.app.config import Settings


@pytest.mark.asyncio
async def test_exa_degrades_without_key():
    client = ExaClient(settings=Settings(exa_api_key=""))
    hits, degraded = await client.search("桃园三结义")
    assert hits == []
    assert degraded is True


@pytest.mark.asyncio
async def test_exa_search_parses_results():
    settings = Settings(exa_api_key="exa-key", exa_base_url="https://api.exa.test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "exa-key"
        assert request.url.path.endswith("/search")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "桃园三结义",
                        "url": "https://example.com/a",
                        "text": "刘备关羽张飞结义。",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        exa = ExaClient(settings=settings, client=http)
        hits, degraded = await exa.search("桃园三结义")
        assert degraded is False
        assert len(hits) == 1
        assert hits[0].title == "桃园三结义"
        assert "刘备" in hits[0].text
