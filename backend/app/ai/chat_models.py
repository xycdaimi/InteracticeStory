from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from backend.app.config import Settings, get_settings


def get_geekai_chat_model(
    *,
    settings: Settings | None = None,
    model: str | None = None,
    temperature: float = 0.4,
) -> ChatOpenAI:
    """GeekAI OpenAI 兼容 Chat API → LangChain ChatOpenAI。"""
    s = settings or get_settings()
    if not s.geekai_api_key:
        raise RuntimeError("GEEKAI_API_KEY is not set")
    return ChatOpenAI(
        model=model or s.chat_model,
        api_key=s.geekai_api_key,
        base_url=s.geekai_base_url.rstrip("/"),
        temperature=temperature,
        timeout=300,
        max_retries=2,
    )


@lru_cache
def get_default_chat_model() -> ChatOpenAI:
    return get_geekai_chat_model()
