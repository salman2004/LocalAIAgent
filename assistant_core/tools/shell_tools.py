"""Arbitrary shell command execution, scoped to one of config.yaml's
workspace.roots (same root convention as fs_tools.py).

This is the highest-risk tool in the registry - it's always in
CONFIRM_REQUIRED_TOOLS (see assistant_core/tools/__init__.py) and must
never run without the user approving the exact command first.
"""

from __future__ import annotations

import asyncio

from assistant_core.tools.fs_tools import WorkspaceError, resolve_root

MAX_OUTPUT_CHARS = 20000
DEFAULT_TIMEOUT_SECONDS = 30


async def run_command(
    command: str, root: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> str:
    try:
        name, root_path = resolve_root(root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
            cwd=str(root_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return f"Error launching command: {exc}"

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"Error: command timed out after {timeout_seconds}s and was killed."

    output = (
        f"[{name}] $ {command}\n"
        f"Exit code: {proc.returncode}\n"
        f"{stdout.decode(errors='replace')}"
    )
    stderr_text = stderr.decode(errors="replace").strip()
    if stderr_text:
        output += f"\n[stderr]\n{stderr_text}"

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return output


def describe_run_command(command: str, root: str | None = None) -> str:
    try:
        name, _root_path = resolve_root(root)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    return f"Run in [{name}]:\n{command}"
