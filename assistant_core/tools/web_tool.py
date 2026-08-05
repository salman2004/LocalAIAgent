"""Live web research tools. These make real outbound HTTP requests —
the one deliberate exception to this project's "fully local" design,
scoped to search/fetch only (no cloud LLM APIs are ever called)."""

import asyncio

import trafilatura
from ddgs import DDGS

from assistant_core.config import get_config

MAX_FETCH_CHARS = 6000


def _search_sync(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def web_search(query: str) -> str:
    cfg = get_config().web_search
    results = await asyncio.to_thread(_search_sync, query, cfg.max_results)
    if not results:
        return "No web results found."

    lines = []
    for i, r in enumerate(results, start=1):
        lines.append(f"[{i}] {r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')}")
    return "\n\n".join(lines)


def _fetch_sync(url: str, timeout: int) -> str | None:
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        return None
    return trafilatura.extract(downloaded)


async def web_fetch(url: str) -> str:
    cfg = get_config().web_search
    text = await asyncio.to_thread(_fetch_sync, url, cfg.fetch_timeout_seconds)
    if not text:
        return f"Could not extract readable content from {url}."
    if len(text) > MAX_FETCH_CHARS:
        text = text[:MAX_FETCH_CHARS] + "\n...[truncated]"
    return text
