"""Local RAG store: chunk text, embed it, and keep it in an embedded
LanceDB table (just files on disk, no server process).
"""

from __future__ import annotations

import lancedb

from assistant_core.config import get_config
from assistant_core.llm_client import embed


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _connect():
    cfg = get_config().rag
    return lancedb.connect(cfg.db_path)


def _open_table(db):
    cfg = get_config().rag
    try:
        return db.open_table(cfg.table_name)
    except (FileNotFoundError, ValueError):
        return None


async def index_document(source: str, text: str) -> int:
    """Chunks `text`, embeds each chunk, and upserts it into the RAG table.
    Returns the number of chunks indexed.
    """
    cfg = get_config().rag
    chunks = chunk_text(text, cfg.chunk_size, cfg.chunk_overlap)
    if not chunks:
        return 0

    vectors = await embed(chunks)
    rows = [
        {"vector": vec, "text": chunk, "source": source}
        for vec, chunk in zip(vectors, chunks)
    ]

    db = _connect()
    table = _open_table(db)
    if table is None:
        db.create_table(cfg.table_name, data=rows)
    else:
        table.add(rows)

    return len(rows)


async def search(query: str, k: int | None = None) -> list[dict]:
    """Returns up to `k` chunks most relevant to `query`, each as
    {"text": ..., "source": ..., "distance": ...}. Empty list if the
    RAG store hasn't been populated yet.
    """
    cfg = get_config().rag
    k = k or cfg.top_k

    db = _connect()
    table = _open_table(db)
    if table is None:
        return []

    [query_vector] = await embed([query])
    results = table.search(query_vector).limit(k).to_list()
    return [
        {"text": r["text"], "source": r["source"], "distance": r["_distance"]}
        for r in results
    ]
