"""真实 GeekAI + LangChain 联调测试。禁止 mock 模型返回。

运行：GEEKAI_API_KEY=... pytest backend/tests/test_geekai_langchain_live.py -m live -v
默认 pytest 收集时跳过（无 live marker 时不跑）。
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage

from backend.app.ai.chat_models import get_geekai_chat_model
from backend.app.config import get_settings

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _require_geekai_key():
    if not get_settings().geekai_api_key and not os.environ.get("GEEKAI_API_KEY"):
        pytest.skip("需要真实 GEEKAI_API_KEY")


@pytest.mark.asyncio
async def test_langchain_chat_openai_geekai_roundtrip():
    """LangChain ChatOpenAI → GeekAI 真实 HTTP 往返。"""
    llm = get_geekai_chat_model()
    resp = await llm.ainvoke([HumanMessage(content="只回复两个字：收到")])
    text = str(resp.content or "").strip()
    assert "收到" in text, f"意外回复: {text!r}"


@pytest.mark.asyncio
async def test_geekai_client_langchain_path_roundtrip():
    """GeekAIClient 默认路径经 LangChain，非 httpx 裸调。"""
    from backend.app.ai.geekai_client import GeekAIClient

    geekai = GeekAIClient()
    data = await geekai.chat([{"role": "user", "content": "只回复：ok"}])
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    assert content.strip(), f"空回复: {data!r}"
