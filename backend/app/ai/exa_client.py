from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.config import Settings, get_settings


@dataclass
class ExaHit:
    title: str
    url: str
    text: str


class ExaClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def available(self) -> bool:
        return bool(self.settings.exa_api_key)

    async def search(self, query: str, num_results: int = 5) -> tuple[list[ExaHit], bool]:
        """Return (hits, degraded). degraded=True when API key missing."""
        if not self.settings.exa_api_key:
            return [], True
        client = await self._get_client()
        r = await client.post(
            f"{self.settings.exa_base_url.rstrip('/')}/search",
            headers={
                "x-api-key": self.settings.exa_api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "num_results": num_results,
                "contents": {"text": True},
            },
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        hits: list[ExaHit] = []
        for item in data.get("results") or []:
            text = ""
            contents = item.get("text") or item.get("contents") or {}
            if isinstance(contents, str):
                text = contents
            elif isinstance(contents, dict):
                text = str(contents.get("text") or "")
            hits.append(
                ExaHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    text=text[:2000],
                )
            )
        return hits, False
