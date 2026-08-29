"""File/folder access, sandboxed to one of config.yaml's workspace.roots.

Every path argument is treated as relative to a named root (the `root`
parameter, defaulting to workspace.default_root). Absolute paths and ".."
segments are rejected outright, and the resolved path is double-checked
to still be inside that root before any I/O happens - two independent
layers so a single bug in one check can't escape the sandbox on its own.

write_file and delete_file are in CONFIRM_REQUIRED_TOOLS (see
assistant_core/tools/__init__.py): they go through the confirmation
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


def root_names() -> list[str]:
    """All configured root names, for building the tool schema's enum."""
    return list(vars(get_config().workspace.roots).keys())


def resolve_root(root_name: str | None) -> tuple[str, Path]:
    """Public entry point for other tool modules (e.g. shell_tools) that
    need a root's name/path but aren't doing path-containment checks of
    their own."""
    return _resolve_root(root_name)


def _resolve_root(root_name: str | None) -> tuple[str, Path]:
    cfg = get_config().workspace
    name = root_name or cfg.default_root
    roots = vars(cfg.roots)
    if name not in roots:
        raise WorkspaceError(
            f"Unknown root {name!r}. Valid roots: {', '.join(roots)}"
        )
    root = Path(roots[name].path)
    root.mkdir(parents=True, exist_ok=True)
    return name, root.resolve()


def _safe_path(relative_path: str, root_name: str | None = None) -> tuple[str, Path, Path]:
    """Returns (root_name, root_path, resolved_path)."""
    name, root = _resolve_root(root_name)
    candidate = Path(relative_path)

    if candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceError(
            f"Path must be relative to the root and can't contain '..': {relative_path!r}"
        )

    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise WorkspaceError(f"Path escapes the [{name}] root: {relative_path!r}")

    return name, root, resolved


async def list_directory(path: str = ".", root: str | None = None) -> str:
    try:
        name, root_path, target = _safe_path(path, root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Not found: [{name}] {path}"
    if not target.is_dir():
        return f"Not a directory: [{name}] {path}"

    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    if not entries:
        return "(empty directory)"

    lines = []
    for entry in entries:
        kind = "dir" if entry.is_dir() else "file"
        size = "" if entry.is_dir() else f" ({entry.stat().st_size} bytes)"
        lines.append(f"[{kind}] {entry.relative_to(root_path)}{size}")
    return "\n".join(lines)


async def read_file(path: str, root: str | None = None) -> str:
    try:
        name, _root_path, target = _safe_path(path, root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Not found: [{name}] {path}"
    if not target.is_file():
        return f"Not a file: [{name}] {path}"

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading [{name}] {path}: {exc}"

    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n...[truncated]"
    return text


async def write_file(path: str, content: str, root: str | None = None) -> str:
    try:
        name, _root_path, target = _safe_path(path, root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to [{name}] {path}"


async def delete_file(path: str, root: str | None = None) -> str:
    try:
        name, _root_path, target = _safe_path(path, root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Not found: [{name}] {path}"
    if target.is_dir():
        return f"Refusing to delete a directory via delete_file: [{name}] {path}"

    target.unlink()
    return f"Deleted [{name}] {path}"


def describe_write(path: str, content: str, root: str | None = None) -> str:
    try:
        name, _root_path, target = _safe_path(path, root)
        exists = target.exists()
    except WorkspaceError as exc:
        return f"Error: {exc}"

    verb = "Overwrite" if exists else "Create"
    snippet = content[:PREVIEW_CHARS]
    if len(content) > PREVIEW_CHARS:
        snippet += "...[truncated]"
    return f"{verb} [{name}] {path} ({len(content)} chars):\n{snippet}"


def describe_delete(path: str, root: str | None = None) -> str:
    name = root or get_config().workspace.default_root
    return f"Permanently delete [{name}] {path}"
