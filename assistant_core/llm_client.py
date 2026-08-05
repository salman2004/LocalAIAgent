"""Thin async wrapper around the two llama.cpp server instances
(chat model + embedding model), both exposing OpenAI-compatible routes.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from assistant_core.config import get_config


async def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calls the chat model server and returns the assistant message object
    (dict with at least "role" and "content", and optionally "tool_calls").
    """
    cfg = get_config().llm
    payload: dict[str, Any] = {
        "model": "local-chat-model",
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{cfg.base_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]


async def stream_chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Streams the chat model's response, yielding each choice object
    (dict with "delta" and possibly "finish_reason") as it arrives, in
    the same shape llama.cpp's OpenAI-compatible SSE stream uses.
    """
    cfg = get_config().llm
    payload: dict[str, Any] = {
        "model": "local-chat-model",
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{cfg.base_url}/v1/chat/completions", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                yield chunk["choices"][0]


async def embed(texts: list[str]) -> list[list[float]]:
    """Calls the embedding model server and returns one vector per input text."""
    cfg = get_config().embeddings
    payload = {"model": "local-embedding-model", "input": texts}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{cfg.base_url}/v1/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Preserve input order regardless of how the server orders "data".
    ordered = sorted(data["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in ordered]
