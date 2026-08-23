from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


def dict_messages_to_lc(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            out.append(SystemMessage(content=str(content)))
        elif role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            tool_calls = m.get("tool_calls") or []
            lc_calls = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments") or "{}"
                if isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = json.loads(raw_args)
                lc_calls.append(
                    {
                        "id": tc.get("id") or f"call_{uuid4().hex[:8]}",
                        "name": fn.get("name") or "",
                        "args": args,
                    }
                )
            out.append(AIMessage(content=str(content or ""), tool_calls=lc_calls))
        elif role == "tool":
            out.append(
                ToolMessage(
                    content=str(content),
                    tool_call_id=m.get("tool_call_id") or "",
                )
            )
    return out


def lc_message_to_dict(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, AIMessage):
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tc.get("id") or f"call_{uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": tc.get("name") or "",
                        "arguments": json.dumps(
                            tc.get("args") or {}, ensure_ascii=False
                        ),
                    },
                }
                for tc in message.tool_calls
            ]
        return payload
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": message.content}
    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    return {"role": "assistant", "content": str(message.content)}


def lc_response_to_openai(message: AIMessage) -> dict[str, Any]:
    return {"choices": [{"message": lc_message_to_dict(message)}]}
