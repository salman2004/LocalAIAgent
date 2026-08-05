from assistant_core import rag


async def rag_search(query: str) -> str:
    results = await rag.search(query)
    if not results:
        return "No results (the local document store is empty or has no relevant match)."

    lines = []
    for i, r in enumerate(results, start=1):
        lines.append(f"[{i}] source: {r['source']}\n{r['text']}")
    return "\n\n".join(lines)
