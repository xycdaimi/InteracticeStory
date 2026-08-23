from __future__ import annotations

import httpx
import pytest

from backend.app.ai.geekai_client import GeekAIClient
from backend.app.config import Settings


@pytest.mark.asyncio
async def test_geekai_chat_posts_completions(httpx_mock=None):
    settings = Settings(
        geekai_api_key="test-key",
        geekai_base_url="https://geekai.test/api/v1",
        chat_model="gpt-5.4-mini",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=settings.geekai_base_url) as client:
        geekai = GeekAIClient(settings=settings, client=client)
        data = await geekai.chat([{"role": "user", "content": "hi"}])
        assert data["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_geekai_requires_key():
    geekai = GeekAIClient(settings=Settings(geekai_api_key=""))
    with pytest.raises(RuntimeError, match="GEEKAI_API_KEY"):
        await geekai.chat([{"role": "user", "content": "hi"}])
