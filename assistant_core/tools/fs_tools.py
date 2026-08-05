"""File/folder access, sandboxed to config.yaml's workspace.root.

Every path argument is treated as relative to that root. Absolute paths
and ".." segments are rejected outright, and the resolved path is
double-checked to still be inside the root before any I/O happens -
two independent layers so a single bug in one check can't escape the
sandbox on its own.

write_file and delete_file are mutating and go through the confirmation
round-trip in orchestrator.py before they ever run. list_directory and
read_file are read-only and execute immediately.
"""

from __future__ import annotations

from pathlib import Path

from assistant_core.config import get_config

MAX_READ_CHARS = 20000
PREVIEW_CHARS = 300


class WorkspaceError(Exception):
    pass


def _workspace_root() -> Path:
    root = Path(get_config().workspace.root)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_path(relative_path: str) -> Path:
    root = _workspace_root()
    candidate = Path(relative_path)

    if candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceError(
            f"Path must be relative to the workspace and can't contain '..': {relative_path!r}"
        )

    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise WorkspaceError(f"Path escapes the workspace: {relative_path!r}")

    return resolved


async def list_directory(path: str = ".") -> str:
    try:
        target = _safe_path(path)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Not found: {path}"
    if not target.is_dir():
        return f"Not a directory: {path}"

    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    if not entries:
        return "(empty directory)"

    root = _workspace_root()
    lines = []
    for entry in entries:
        kind = "dir" if entry.is_dir() else "file"
        size = "" if entry.is_dir() else f" ({entry.stat().st_size} bytes)"
        lines.append(f"[{kind}] {entry.relative_to(root)}{size}")
    return "\n".join(lines)


async def read_file(path: str) -> str:
    try:
        target = _safe_path(path)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Not found: {path}"
    if not target.is_file():
        return f"Not a file: {path}"

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading {path}: {exc}"

    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n...[truncated]"
    return text


async def write_file(path: str, content: str) -> str:
    try:
        target = _safe_path(path)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {path}"


async def delete_file(path: str) -> str:
    try:
        target = _safe_path(path)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Not found: {path}"
    if target.is_dir():
        return f"Refusing to delete a directory via delete_file: {path}"

    target.unlink()
    return f"Deleted {path}"


def describe_write(path: str, content: str) -> str:
    try:
        target = _safe_path(path)
        exists = target.exists()
    except WorkspaceError as exc:
        return f"Error: {exc}"

    verb = "Overwrite" if exists else "Create"
    snippet = content[:PREVIEW_CHARS]
    if len(content) > PREVIEW_CHARS:
        snippet += "...[truncated]"
    return f"{verb} {path} ({len(content)} chars):\n{snippet}"


def describe_delete(path: str) -> str:
    return f"Permanently delete {path}"
