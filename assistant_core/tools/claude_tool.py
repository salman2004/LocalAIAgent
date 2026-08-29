"""Escalation to Claude Code CLI (headless), for tasks the local model
shouldn't attempt itself - primarily anything involving writing/editing
code. Shells out to the user's already-authenticated `claude` CLI, reusing
their existing Claude Code login/subscription rather than a metered
Anthropic API key.

Invocation flags, verified by hand against this machine's Claude Code CLI
(2.1.251) before relying on them:
- `-p`/`--print`: headless/non-interactive, no TTY needed, doesn't hang.
- `--restricted`: strips Bash/PowerShell/REPL/WebFetch and confines file
  access to `--add-dir` - the local agent already has its own gated
  run_command, so this path deliberately can't run shell commands too.
- `--restricted` ALONE also blocks the Write tool (confirmed by a real
  test run: the write was silently denied). `--permission-mode
  acceptEdits` is required alongside it to actually allow file edits
  while keeping `--restricted`'s command/network lockdown.
- `--output-format json` gives a single structured result with a `result`
  text field, an `is_error` flag, and a `permission_denials` list.

Always in CONFIRM_REQUIRED_TOOLS (see assistant_core/tools/__init__.py):
it can write files just like write_file, so it gets the same approval
gate, and its (possibly multi-minute) run shows up via the same
tool_start/tool_end status events the orchestrator already emits around
every gated tool call.
"""

from __future__ import annotations

import asyncio
import json

from assistant_core.tools.fs_tools import WorkspaceError, resolve_root

MAX_OUTPUT_CHARS = 20000
DEFAULT_TIMEOUT_SECONDS = 180
PREVIEW_CHARS = 300


async def ask_claude(
    prompt: str, root: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> str:
    try:
        _name, root_path = resolve_root(root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            "--restricted",
            "--permission-mode",
            "acceptEdits",
            "--add-dir",
            str(root_path),
            "--output-format",
            "json",
            prompt,
            cwd=str(root_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return f"Error launching Claude Code: {exc}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return f"Error: escalation to Claude Code timed out after {timeout_seconds}s and was killed."

    if proc.returncode != 0:
        err_text = stderr.decode(errors="replace").strip()
        return f"Error: Claude Code exited with code {proc.returncode}.\n{err_text}"

    try:
        payload = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError:
        text = stdout.decode(errors="replace").strip()
        return text[:MAX_OUTPUT_CHARS] if text else "Error: Claude Code returned no output."

    if payload.get("is_error"):
        return f"Error from Claude Code: {payload.get('result', '(no message)')}"

    result_text = payload.get("result") or "(Claude Code returned no result text)"

    denials = payload.get("permission_denials") or []
    if denials:
        denied_tools = ", ".join(sorted({d.get("tool_name", "?") for d in denials}))
        result_text += (
            f"\n\n[Note: Claude Code's own permission settings denied: {denied_tools}]"
        )

    if len(result_text) > MAX_OUTPUT_CHARS:
        result_text = result_text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return result_text


def describe_ask_claude(prompt: str, root: str | None = None) -> str:
    try:
        name, _root_path = resolve_root(root)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    preview = prompt[:PREVIEW_CHARS]
    if len(prompt) > PREVIEW_CHARS:
        preview += "...[truncated]"
    return f"Escalate to Claude Code in [{name}]:\n{preview}"
