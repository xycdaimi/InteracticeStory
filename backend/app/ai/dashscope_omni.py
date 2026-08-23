from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx

from backend.app.ai.errors import raise_if_quota_error
from backend.app.config import Settings, get_settings

QC_SYSTEM_SCOPE = (
    "【审查范围】仅判断上述单段视频内部是否合理。"
    "不要评价该片段与任何前驱、后继或其他片段之间的衔接、连贯性或剧情承接。"
)

QC_CHECKLIST = """【检查项】仅针对本段视频画面与音频：
- 人物外观是否与设定大体一致
- 场景环境是否与描述相符
- 台词/动作是否与本镜剧本一致
- 画面是否存在明显崩坏、乱码、黑屏等技术问题"""

QC_FORBIDDEN_FAIL_REASONS = (
    "【禁止的 fail 理由】不得以「与上一段不连贯」「衔接生硬」「剧情跳跃」"
    "「与前驱不符」等片段间关系作为 fail 理由。"
)


def build_review_video_user_text(context: str) -> str:
    return (
        f"{context}\n\n"
        f"{QC_SYSTEM_SCOPE}\n\n"
        f"{QC_CHECKLIST}\n\n"
        f"{QC_FORBIDDEN_FAIL_REASONS}\n\n"
        "请判断该视频片段是否合格。只输出 JSON："
        '{"status":"pass"|"fail","reasons":["..."]}。'
        "fail 时 reasons 仅说明本段内部的人设/场景/剧本/画质等问题。"
    )


def _normalize_qc_model(model: str) -> str:
    return model.strip().lower()


class DashScopeOmniClient:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.dashscope_base_url.rstrip("/"),
                timeout=httpx.Timeout(10.0, read=300.0, write=60.0, pool=30.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _video_data_uri(path: Path) -> str:
        data = base64.b64encode(path.read_bytes()).decode()
        return f"data:video/mp4;base64,{data}"

    async def _chat_completion_text(self, *, model: str, messages: list[dict[str, Any]]) -> str:
        client = await self._get_client()
        parts: list[str] = []
        async with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "modalities": ["text"],
                "stream_options": {"include_usage": True},
            },
            headers={
                "Authorization": f"Bearer {self.settings.dashscope_api_key}",
                "Content-Type": "application/json",
            },
        ) as response:
            raw_body: list[str] = []
            async for line in response.aiter_lines():
                raw_body.append(line)
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                chunk = json.loads(payload)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    parts.append(content)

            body = "\n".join(raw_body)
            raise_if_quota_error(
                provider="dashscope", model=model, status=response.status_code, body=body
            )
            response.raise_for_status()

        text = "".join(parts).strip()
        if not text:
            raise RuntimeError("DashScope QC response empty")
        return text

    async def review_video(
        self,
        *,
        video_path: Path,
        context: str,
    ) -> dict[str, Any]:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")
        model = _normalize_qc_model(self.settings.video_qc_model)
        user_content = [
            {"type": "video_url", "video_url": {"url": self._video_data_uri(video_path)}},
            {"type": "text", "text": build_review_video_user_text(context)},
        ]
        text = await self._chat_completion_text(
            model=model,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_qc_json(text)


def _parse_qc_json(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise RuntimeError(f"QC response not JSON: {text[:200]}")
    obj = json.loads(m.group())
    status = obj.get("status", "fail")
    if status not in ("pass", "fail"):
        status = "fail"
    reasons = obj.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    return {"status": status, "reasons": [str(x) for x in reasons]}
