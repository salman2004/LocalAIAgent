"""Escalation to Claude Code CLI (headless), for tasks the local model
shouldn't attempt itself - primarily anything involving writing/editing
code. Shells out to the user's already-authenticated `claude` CLI, reusing
their existing Claude Code login/subscription rather than a metered
Anthropic API key.

Escalations share ONE persistent Claude Code session (not a fresh one per
call), so the escalation path accumulates memory across separate asks -
"finish what we started earlier" actually works. The session id is
pinned once (--session-id) and resumed on every later call (--resume);
verified by hand: teaching a session a fact in one call and recalling it
via --resume in a separate call actually works. If a resume ever fails
(e.g. the local session store was cleared), a fresh session is started
and the state file updated - transparent to the caller, just one retry.

Every call - success or failure - is logged as one JSON line to
workspace/ask_claude_log.jsonl (inside the "code" root), so the
assistant's own read_file tool can inspect its own escalation history
when asked something like "how have your escalations gone lately?".

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
  text field, an `is_error` flag, `session_id`, cost/usage stats, and a
  `permission_denials` list.
- `--session-id <uuid>` pins a specific id for a brand-new session;
  `--resume <uuid>` continues an existing one.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from assistant_core.tools.fs_tools import WorkspaceError, resolve_root

MAX_OUTPUT_CHARS = 20000
DEFAULT_TIMEOUT_SECONDS = 180
PREVIEW_CHARS = 300

STATE_DIR = Path(__file__).resolve().parent.parent.parent / ".state"
SESSION_FILE = STATE_DIR / "ask_claude_session.json"
LOG_ROOT = "code"
LOG_FILENAME = "ask_claude_log.jsonl"


def _load_session_id() -> str | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("session_id")
    except (OSError, json.JSONDecodeError):
        return None


def _save_session_id(session_id: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")


def _append_log(entry: dict) -> None:
    entry = {"ts": time.time(), **entry}
    try:
        _name, root_path = resolve_root(LOG_ROOT)
        with open(root_path / LOG_FILENAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except (WorkspaceError, OSError):
        pass  # logging is best-effort, never let it break the actual escalation


async def _run_claude(
    prompt: str, root_path: Path, timeout_seconds: int, session_flag: list[str]
) -> tuple[int, bytes, bytes]:
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
        *session_flag,
        prompt,
        cwd=str(root_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"timed out after {timeout_seconds}s and was killed")
    return proc.returncode, stdout, stderr


async def ask_claude(
    prompt: str, root: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> str:
    try:
        name, root_path = resolve_root(root)
    except WorkspaceError as exc:
        return f"Error: {exc}"

    start = time.monotonic()
    existing_session = _load_session_id()
    if existing_session:
        session_flag = ["--resume", existing_session]
    else:
        existing_session = str(uuid.uuid4())
        _save_session_id(existing_session)
        session_flag = ["--session-id", existing_session]

    try:
        returncode, stdout, stderr = await _run_claude(prompt, root_path, timeout_seconds, session_flag)
    except (TimeoutError, OSError) as exc:
        _append_log({"root": name, "ok": False, "error": str(exc)})
        return f"Error: {exc}" if isinstance(exc, TimeoutError) else f"Error launching Claude Code: {exc}"

    # A non-zero exit while resuming likely means the stored session id
    # went stale (e.g. the local session store was cleared) - retry once
    # with a brand-new session rather than failing the whole call.
    if returncode != 0 and session_flag[0] == "--resume":
        fresh_id = str(uuid.uuid4())
        _save_session_id(fresh_id)
        try:
            returncode, stdout, stderr = await _run_claude(
                prompt, root_path, timeout_seconds, ["--session-id", fresh_id]
            )
        except (TimeoutError, OSError) as exc:
            _append_log({"root": name, "ok": False, "error": str(exc)})
            return f"Error: {exc}"

    duration_s = round(time.monotonic() - start, 1)

    if returncode != 0:
        err_text = stderr.decode(errors="replace").strip()
        _append_log({"root": name, "ok": False, "error": err_text, "duration_s": duration_s})
        return f"Error: Claude Code exited with code {returncode}.\n{err_text}"

    try:
        payload = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError:
        text = stdout.decode(errors="replace").strip()
        _append_log({"root": name, "ok": bool(text), "duration_s": duration_s, "note": "non-JSON output"})
        return text[:MAX_OUTPUT_CHARS] if text else "Error: Claude Code returned no output."

    if payload.get("session_id"):
        _save_session_id(payload["session_id"])

    is_error = bool(payload.get("is_error"))
    result_text = payload.get("result") or "(Claude Code returned no result text)"

    denials = payload.get("permission_denials") or []
    if denials:
        denied_tools = ", ".join(sorted({d.get("tool_name", "?") for d in denials}))
        result_text += f"\n\n[Note: Claude Code's own permission settings denied: {denied_tools}]"

    _append_log(
        {
            "root": name,
            "ok": not is_error,
            "duration_s": duration_s,
            "cost_usd": payload.get("total_cost_usd"),
            "num_turns": payload.get("num_turns"),
            "result_preview": result_text[:PREVIEW_CHARS],
        }
    )

    if len(result_text) > MAX_OUTPUT_CHARS:
        result_text = result_text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"

    return f"Error from Claude Code: {result_text}" if is_error else result_text


def describe_ask_claude(prompt: str, root: str | None = None) -> str:
    try:
        name, _root_path = resolve_root(root)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    preview = prompt[:PREVIEW_CHARS]
    if len(prompt) > PREVIEW_CHARS:
        preview += "...[truncated]"
    return f"Escalate to Claude Code in [{name}]:\n{preview}"
