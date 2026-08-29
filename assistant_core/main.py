"""FastAPI "assistant core" - the one long-running service that owns the
tool-calling loop, RAG store, and file/web tools. The terminal UI (cli/tui.py)
and the plain CLI fallback (cli/chat.py) are thin clients that just talk to
this over HTTP.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from assistant_core import confirmations, orchestrator
from assistant_core.config import get_config

app = FastAPI(title="Local Assistant Core")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: ChatMessage
    messages: list[ChatMessage]


class ConfirmRequest(BaseModel):
    id: str
    approved: bool


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    raw_messages = [m.model_dump(exclude_none=True) for m in request.messages]
    updated = await orchestrator.run_chat(raw_messages)
    return ChatResponse(reply=updated[-1], messages=updated)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    raw_messages = [m.model_dump(exclude_none=True) for m in request.messages]

    async def event_source():
        try:
            async for event in orchestrator.stream_chat(raw_messages):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.post("/chat/confirm")
async def chat_confirm(request: ConfirmRequest):
    resolved = confirmations.resolve(request.id, request.approved)
    if not resolved:
        return {"ok": False, "reason": "unknown or already-resolved confirmation id"}
    return {"ok": True}


# Registered last so it never shadows the API routes above - StaticFiles
# only serves whatever a preceding route hasn't already claimed. Same
# origin as the API, so the web UI needs no CORS setup at all.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    cfg = get_config().assistant_core
    uvicorn.run("assistant_core.main:app", host=cfg.host, port=cfg.port)
