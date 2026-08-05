"""In-memory registry of tool-call confirmations pending a user's yes/no.

Bridges the /chat/stream <-> /chat/confirm round-trip: the streaming
request awaits a Future that a separate /chat/confirm request resolves.
Both requests are handled by the same process/event loop, so a plain
module-level dict is enough - no external store needed.
"""

import asyncio

CONFIRMATION_TIMEOUT_SECONDS = 300

_pending: dict[str, asyncio.Future] = {}


def create(request_id: str) -> asyncio.Future:
    fut = asyncio.get_event_loop().create_future()
    _pending[request_id] = fut
    return fut


def resolve(request_id: str, approved: bool) -> bool:
    fut = _pending.pop(request_id, None)
    if fut is None or fut.done():
        return False
    fut.set_result(approved)
    return True


def discard(request_id: str) -> None:
    _pending.pop(request_id, None)
