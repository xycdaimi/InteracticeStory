from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx

from backend.app.ai.errors import QuotaExhaustedError, raise_if_quota_error
from backend.app.config import Settings, get_settings
from backend.app.infrastructure.paths import story_dir
from backend.app.services.video_duration import clamp_duration


class EphoneVideoClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.ephone_base_url.rstrip("/"),
                timeout=httpx.Timeout(10.0, read=120.0, write=60.0, pool=30.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        if not self.settings.ephone_api_key:
            raise RuntimeError("EPHONE_API_KEY is not set")
        return {
            "Authorization": f"Bearer {self.settings.ephone_api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _encode_image(path: Path) -> str:
        data = base64.b64encode(path.read_bytes()).decode()
        return f"data:image/png;base64,{data}"

    async def submit(
        self,
        *,
        model: str,
        prompt: str = "",
        first_frame: Path | None = None,
        ratio: str | None = None,
        duration: int | None = None,
        source_task_id: str | None = None,
    ) -> str:
        client = await self._get_client()
        if source_task_id:
            inp: dict[str, Any] = {
                "source_task_id": source_task_id,
                "resolution": self.settings.video_resolution,
            }
        else:
            if duration is None:
                raise ValueError("duration is required for video generation submit")
            dur = clamp_duration(int(duration))
            inp = {
                "prompt": prompt,
                "ratio": ratio or self.settings.video_default_ratio,
                "duration": dur,
                "resolution": self.settings.video_resolution,
            }
            if first_frame is not None:
                inp["first_frame_image"] = self._encode_image(first_frame)

        r = await client.post(
            "/v1/task/submit",
            json={"model": model, "input": inp},
            headers=self._headers(),
        )
        body = r.text
        raise_if_quota_error(provider="ephone", model=model, status=r.status_code, body=body)
        r.raise_for_status()
        data = r.json()
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"ephone submit missing task id: {data}")
        return str(task_id)

    async def poll(self, task_id: str) -> dict[str, Any]:
        client = await self._get_client()
        r = await client.get(f"/v1/task/{task_id}", headers=self._headers())
        body = r.text
        raise_if_quota_error(
            provider="ephone",
            model=self.settings.video_model,
            status=r.status_code,
            body=body,
        )
        r.raise_for_status()
        return r.json()

    async def wait_for_outputs(
        self,
        task_id: str,
        *,
        poll_interval: float = 3.0,
        max_polls: int = 200,
    ) -> list[str]:
        for _ in range(max_polls):
            data = await self.poll(task_id)
            status = data.get("status")
            if status == "completed":
                outputs = data.get("outputs") or []
                urls = []
                for item in outputs:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        u = item.get("url") or item.get("video_url")
                        if u:
                            urls.append(u)
                if not urls:
                    raise RuntimeError(f"ephone task completed without outputs: {data}")
                return urls
            if status == "failed":
                raise RuntimeError(f"ephone task failed: {data.get('error') or data}")
            await asyncio.sleep(poll_interval)
        raise RuntimeError(f"ephone task {task_id} timed out")

    async def download_video(self, url: str, dest: Path) -> Path:
        client = await self._get_client()
        r = await client.get(url)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest

    async def create_and_wait(
        self,
        *,
        prompt: str,
        first_frame: Path,
        dest: Path,
        duration: int,
        model: str | None = None,
    ) -> Path:
        task_id = await self.submit(
            model=model or self.settings.video_model,
            prompt=prompt,
            first_frame=first_frame,
            duration=duration,
        )
        urls = await self.wait_for_outputs(task_id)
        return await self.download_video(urls[0], dest)

    async def regenerate_and_wait(
        self,
        *,
        source_task_id: str,
        dest: Path,
    ) -> Path:
        task_id = await self.submit(
            model=self.settings.video_regen_model,
            prompt="",
            source_task_id=source_task_id,
        )
        urls = await self.wait_for_outputs(task_id)
        return await self.download_video(urls[0], dest)
