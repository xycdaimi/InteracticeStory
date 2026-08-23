from __future__ import annotations

from typing import Any

import httpx

from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.ai.message_compat import dict_messages_to_lc, lc_response_to_openai
from backend.app.ai.errors import raise_if_quota_error
from backend.app.config import Settings, get_settings


class GeekAIClient:
    """GeekAI Chat Completions；底层经 LangChain ChatOpenAI 调用。"""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._inject_client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._inject_client is None:
            self._inject_client = httpx.AsyncClient(
                base_url=self.settings.geekai_base_url.rstrip("/"),
                timeout=httpx.Timeout(10.0, read=300.0, write=60.0, pool=30.0),
            )
        return self._inject_client

    async def aclose(self) -> None:
        if self._inject_client is not None:
            await self._inject_client.aclose()
            self._inject_client = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> dict[str, Any]:
        if not self.settings.geekai_api_key:
            raise RuntimeError("GEEKAI_API_KEY is not set")

        # 测试注入 httpx client 时走直连
        if self._inject_client is not None:
            return await self._chat_httpx(messages, tools=tools, model=model, tool_choice=tool_choice)

        llm = get_geekai_chat_model(settings=self.settings, model=model)
        if tools:
            llm = llm.bind_tools(tools)
            if tool_choice is not None:
                llm = llm.bind(tool_choice=tool_choice)
        lc_messages = dict_messages_to_lc(messages)
        response = await llm.ainvoke(lc_messages)
        return lc_response_to_openai(response)

    async def _chat_httpx(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        model: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.settings.chat_model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        client = await self._get_client()
        r = await client.post(
            "/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.settings.geekai_api_key}",
                "Content-Type": "application/json",
            },
        )
        body = r.text
        raise_if_quota_error(
            provider="geekai",
            model=payload["model"],
            status=r.status_code,
            body=body,
        )
        r.raise_for_status()
        return r.json()
