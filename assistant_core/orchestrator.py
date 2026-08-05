"""The actual "brain" loop: send the conversation to the chat model,
and if it asks for a tool call, run the tool and feed the result back,
repeating until the model returns a plain answer (or we hit the
iteration cap, as a safety net against a runaway tool-call loop).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

from assistant_core import confirmations
from assistant_core.config import get_config
from assistant_core.llm_client import chat_completion, stream_chat_completion
from assistant_core.tools import (
    MUTATING_TOOLS,
    TOOL_FUNCTIONS,
    TOOL_SPECS,
    describe_pending_call,
)

SYSTEM_PROMPT = (
    "You are a local, offline-first assistant running entirely on the "
    "user's own hardware. You help with reasoning, coding, and research. "
    "Tools available: rag_search (the user's own ingested documents), "
    "web_search/web_fetch (the live web - use these whenever you don't "
    "already know something, rather than guessing), and list_directory/"
    "read_file/write_file/delete_file (the user's workspace folder). "
    "Prefer rag_search first when the question might be about the user's "
    "own material. Cite sources (file name or URL) when you use a tool "
    "result in your answer. write_file and delete_file require the user's "
    "explicit approval and may be denied - if denied, say so plainly "
    "rather than pretending the action happened."
)


async def _execute_tool_call(call: dict) -> str:
    name = call["function"]["name"]
    try:
        args = json.loads(call["function"]["arguments"] or "{}")
    except json.JSONDecodeError:
        args = {}

    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return f"Error: unknown tool '{name}'."
    try:
        return await func(args)
    except Exception as exc:  # tool failures shouldn't crash the chat
        return f"Error running tool '{name}': {exc}"


async def run_chat(messages: list[dict]) -> list[dict]:
    """Takes the full conversation so far (without a system message — this
    function injects one if missing) and returns the updated conversation,
    including any tool-call turns, ending in a final assistant message.
    """
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    max_iterations = get_config().assistant_core.max_tool_iterations

    for _ in range(max_iterations):
        assistant_message = await chat_completion(messages, tools=TOOL_SPECS)
        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls")
        if not tool_calls:
            return messages

        for call in tool_calls:
            name = call["function"]["name"]
            if name in MUTATING_TOOLS:
                # No interactive channel on this endpoint to ask for
                # approval, so mutating actions are refused rather than
                # either hanging forever or running unconfirmed.
                result = (
                    f"'{name}' requires interactive approval, which isn't "
                    "available on this endpoint. Use the terminal UI (cli/tui.py) "
                    "for file writes/deletes."
                )
            else:
                result = await _execute_tool_call(call)
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": result}
            )

    return messages


async def stream_chat(messages: list[dict]) -> AsyncIterator[dict]:
    """Same tool-calling loop as run_chat, but streams progress as it
    happens: {"type": "thinking", "content": ...} for reasoning tokens,
    {"type": "delta", "content": ...} for the actual answer text,
    {"type": "tool_start"/"tool_end", "name": ...} around read-only tool
    calls, {"type": "confirm_request"/"confirm_resolved", ...} around
    mutating ones, and finally {"type": "done", "messages": [...]} with
    the full updated conversation (mirroring run_chat's return value).
    """
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    max_iterations = get_config().assistant_core.max_tool_iterations

    for _ in range(max_iterations):
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}

        async for choice in stream_chat_completion(messages, tools=TOOL_SPECS):
            delta = choice.get("delta", {})

            if delta.get("reasoning_content"):
                yield {"type": "thinking", "content": delta["reasoning_content"]}

            if delta.get("content"):
                content_parts.append(delta["content"])
                yield {"type": "delta", "content": delta["content"]}

            for tc in delta.get("tool_calls") or []:
                slot = tool_calls_acc.setdefault(
                    tc["index"], {"id": None, "name": "", "arguments": ""}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                func = tc.get("function") or {}
                if func.get("name"):
                    slot["name"] += func["name"]
                if func.get("arguments"):
                    slot["arguments"] += func["arguments"]

        assistant_message: dict = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
        }

        if tool_calls_acc:
            ordered_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            assistant_message["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in ordered_calls
            ]

        messages.append(assistant_message)

        if not tool_calls_acc:
            yield {"type": "done", "messages": messages}
            return

        for call in assistant_message["tool_calls"]:
            name = call["function"]["name"]

            if name in MUTATING_TOOLS:
                try:
                    preview_args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    preview_args = {}

                request_id = uuid.uuid4().hex
                yield {
                    "type": "confirm_request",
                    "id": request_id,
                    "tool": name,
                    "preview": describe_pending_call(name, preview_args),
                }

                fut = confirmations.create(request_id)
                try:
                    approved = await asyncio.wait_for(
                        fut, timeout=confirmations.CONFIRMATION_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    confirmations.discard(request_id)
                    approved = False

                yield {"type": "confirm_resolved", "id": request_id, "approved": approved}

                if not approved:
                    result = "Denied by the user (or the confirmation timed out)."
                else:
                    yield {"type": "tool_start", "name": name}
                    result = await _execute_tool_call(call)
                    yield {"type": "tool_end", "name": name}
            else:
                yield {"type": "tool_start", "name": name}
                result = await _execute_tool_call(call)
                yield {"type": "tool_end", "name": name}

            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": result}
            )

    yield {"type": "done", "messages": messages}
