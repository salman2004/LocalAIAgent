"""Tool registry: OpenAI-style function specs handed to the chat model,
plus the actual callables the orchestrator dispatches to when the model
requests a tool call.
"""

from assistant_core.tools import claude_tool, fs_tools, shell_tools
from assistant_core.tools.rag_tool import rag_search
from assistant_core.tools.web_tool import web_fetch, web_search

_ROOT_PARAM = {
    "type": "string",
    "enum": fs_tools.root_names(),
    "description": (
        "Which configured location to use (see the system prompt for what "
        "each one is). Defaults to the workspace's default root if omitted."
    ),
}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "Search the local document store (notes, PDFs, code, etc. "
                "that the user has ingested) for passages relevant to a query. "
                "Use this before web_search when the answer might already be "
                "in the user's own material."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web and return a list of results (title, "
                "URL, snippet). Use web_fetch afterwards to read the full "
                "text of a promising result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return its main readable text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and folders inside one of the assistant's "
                "configured roots. Paths are relative to that root; use "
                "'.' for the top level."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to list. Defaults to '.'."},
                    "root": _ROOT_PARAM,
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from one of the assistant's configured roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file."},
                    "root": _ROOT_PARAM,
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a text file in one of the assistant's "
                "configured roots. Requires the user's explicit approval "
                "before it runs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file."},
                    "content": {"type": "string", "description": "Full contents to write."},
                    "root": _ROOT_PARAM,
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Permanently delete a file in one of the assistant's "
                "configured roots. Requires the user's explicit approval "
                "before it runs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file."},
                    "root": _ROOT_PARAM,
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a PowerShell command inside one of the assistant's "
                "configured roots and return its output. Requires the "
                "user's explicit approval before it runs - use this "
                "sparingly, only when a file/search tool genuinely can't "
                "do the job."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The PowerShell command to run."},
                    "root": _ROOT_PARAM,
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Kill the command if it runs longer than this. Defaults to 30.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_claude",
            "description": (
                "Escalate a task to Claude Code (a much more capable coding "
                "agent) instead of attempting it yourself. ALWAYS use this "
                "for any task that involves writing, editing, or debugging "
                "code, however small - you must never write code yourself. "
                "Also use it for any other task complex enough that you're "
                "not confident handling it directly. Requires the user's "
                "explicit approval before it runs, and can take a couple of "
                "minutes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The full task/request to hand to Claude Code, with enough context to act on its own.",
                    },
                    "root": _ROOT_PARAM,
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Kill the escalation if it runs longer than this. Defaults to 180.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "rag_search": lambda args: rag_search(args["query"]),
    "web_search": lambda args: web_search(args["query"]),
    "web_fetch": lambda args: web_fetch(args["url"]),
    "list_directory": lambda args: fs_tools.list_directory(args.get("path", "."), args.get("root")),
    "read_file": lambda args: fs_tools.read_file(args["path"], args.get("root")),
    "write_file": lambda args: fs_tools.write_file(args["path"], args["content"], args.get("root")),
    "delete_file": lambda args: fs_tools.delete_file(args["path"], args.get("root")),
    "run_command": lambda args: shell_tools.run_command(
        args["command"], args.get("root"), args.get("timeout_seconds", shell_tools.DEFAULT_TIMEOUT_SECONDS)
    ),
    "ask_claude": lambda args: claude_tool.ask_claude(
        args["prompt"], args.get("root"), args.get("timeout_seconds", claude_tool.DEFAULT_TIMEOUT_SECONDS)
    ),
}

# Tools in this set go through the confirmation round-trip in
# orchestrator.py instead of executing immediately - anything mutating
# (write_file/delete_file) or otherwise risky/irreversible (run_command,
# ask_claude).
CONFIRM_REQUIRED_TOOLS = {"write_file", "delete_file", "run_command", "ask_claude"}


def describe_pending_call(name: str, args: dict) -> str:
    """Human-readable preview of a gated call, shown to the user before
    they approve or deny it."""
    if name == "write_file":
        return fs_tools.describe_write(args.get("path", ""), args.get("content", ""), args.get("root"))
    if name == "delete_file":
        return fs_tools.describe_delete(args.get("path", ""), args.get("root"))
    if name == "run_command":
        return shell_tools.describe_run_command(args.get("command", ""), args.get("root"))
    if name == "ask_claude":
        return claude_tool.describe_ask_claude(args.get("prompt", ""), args.get("root"))
    return f"{name}({args})"
