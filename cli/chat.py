"""Thin CLI client for the assistant core. Talks to it purely over HTTP,
the same way a future voice front-end will — no direct imports from
assistant_core, on purpose.
"""

import sys

import httpx
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _core_url() -> str:
    with open(REPO_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    core = cfg["assistant_core"]
    return f"http://{core['host']}:{core['port']}"


def main():
    base_url = _core_url()
    messages = []

    print("Local assistant CLI. Type 'exit' or 'quit' to leave.\n")

    with httpx.Client(timeout=180.0) as client:
        while True:
            try:
                user_input = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break

            messages.append({"role": "user", "content": user_input})

            try:
                resp = client.post(f"{base_url}/chat", json={"messages": messages})
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"[error contacting assistant core: {exc}]")
                messages.pop()  # don't keep a dangling user turn on failure
                continue

            data = resp.json()
            messages = data["messages"]
            reply = data["reply"]
            print(f"assistant> {reply.get('content', '')}\n")


if __name__ == "__main__":
    sys.exit(main())
