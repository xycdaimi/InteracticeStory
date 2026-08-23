from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from backend.app.ai.errors import raise_if_quota_error
from backend.app.config import Settings, get_settings


class GeekAIImageClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.geekai_base_url.rstrip("/"),
                timeout=httpx.Timeout(10.0, read=300.0, write=60.0, pool=30.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate_png(
        self,
        *,
        model: str,
        prompt: str,
        dest: Path,
        size: str = "1024x1024",
    ) -> Path:
        if not self.settings.geekai_api_key:
            raise RuntimeError("GEEKAI_API_KEY is not set")

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }
        client = await self._get_client()
        r = await client.post(
            "/images/generations",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.settings.geekai_api_key}",
                "Content-Type": "application/json",
            },
        )
        body = r.text
        raise_if_quota_error(provider="geekai", model=model, status=r.status_code, body=body)
        if r.status_code >= 400:
            detail = body
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict) and parsed.get("message"):
                    detail = str(parsed["message"])
            except json.JSONDecodeError:
                pass
            raise RuntimeError(
                f"GeekAI image rejected ({r.status_code}): {detail[:500]}"
            )
        data = r.json()
        items = data.get("data") or []
        if not items:
            raise RuntimeError(f"GeekAI image response missing data: {data}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        item = items[0]
        if item.get("b64_json"):
            dest.write_bytes(base64.b64decode(item["b64_json"]))
            return dest
        if item.get("url"):
            img = await client.get(item["url"])
            img.raise_for_status()
            dest.write_bytes(img.content)
            return dest
        raise RuntimeError(f"GeekAI image response has no b64_json or url: {item}")
