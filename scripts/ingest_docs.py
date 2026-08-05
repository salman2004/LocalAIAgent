"""Walks a folder and indexes text files into the local RAG store.

Usage:
    python scripts/ingest_docs.py --path C:\\path\\to\\notes

Requires the embedding server (scripts/start_embedding_server.ps1) to
already be running, since indexing calls out to it to embed chunks.

PDFs and other binary formats aren't handled yet — convert to .txt/.md
first, or extend `EXTENSIONS` and add an extraction step for the format
you need.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant_core import rag  # noqa: E402

EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv"}


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            yield path


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="File or folder to ingest.")
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"Path not found: {root}")
        return 1

    total_chunks = 0
    total_files = 0
    for file_path in iter_files(root):
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(f"skip {file_path}: {exc}")
            continue

        n = await rag.index_document(str(file_path), text)
        if n:
            total_files += 1
            total_chunks += n
            print(f"indexed {file_path} ({n} chunks)")

    print(f"\nDone. {total_files} files, {total_chunks} chunks indexed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
