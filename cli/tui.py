"""Terminal UI for the assistant, built with Textual. Talks to
assistant_core purely over HTTP (POST /chat/stream, /chat/confirm) - the
same protocol a browser client would use - so this file has no import
dependency on the assistant_core package itself.

Run with: python -m cli.tui
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml
from rich.markup import escape
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Collapsible, Footer, Header, Input, Markdown, Static

REPO_ROOT = Path(__file__).resolve().parent.parent

WELCOME_TEXT = (
    "Local assistant - reasoning, coding, research, and workspace file access.\n"
    "Type a message and press enter. Ctrl+Q to quit."
)


def _core_base_url() -> str:
    with open(REPO_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    core = cfg["assistant_core"]
    return f"http://{core['host']}:{core['port']}"


def line_user(text: str) -> str:
    return f"[bold cyan]you[/bold cyan] [cyan]>[/cyan] {escape(text)}"


def line_tool(text: str) -> str:
    return f"[dim]⏺ {escape(text)}[/dim]"


def line_error(text: str) -> str:
    return f"[bold red]error:[/bold red] {escape(text)}"


class ConfirmScreen(ModalScreen[bool]):
    """Modal shown when the model wants to run a mutating file tool.
    Blocks until the user presses y/n (or clicks nothing - there are no
    buttons on purpose, keyboard-only keeps it fast)."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-box {
        width: 70%;
        max-width: 90;
        border: heavy $warning;
        background: $surface;
        padding: 1 2;
    }
    #confirm-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    #confirm-preview {
        margin-bottom: 1;
    }
    #confirm-hint {
        color: $text-muted;
    }
    """

    def __init__(self, tool: str, preview: str) -> None:
        super().__init__()
        self.tool = tool
        self.preview = preview

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(f"Approve {self.tool}?", id="confirm-title")
            yield Static(escape(self.preview), id="confirm-preview")
            yield Static("[y] approve      [n] deny", id="confirm-hint")

    def on_key(self, event: events.Key) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)


class LocalAssistantApp(App):
    TITLE = "◆ LOCAL ASSISTANT"

    CSS = """
    Screen {
        background: $background;
    }
    #transcript {
        padding: 1 2;
    }
    #welcome {
        color: $text-muted;
        margin-bottom: 1;
    }
    .user-line {
        margin: 1 0 0 0;
    }
    .tool-line {
        margin: 0 0 0 2;
    }
    Collapsible {
        margin: 1 0 0 0;
    }
    .assistant-answer {
        margin: 1 0 0 0;
    }
    #status {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        background: $surface;
    }
    #input {
        margin: 0 1 1 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.base_url = _core_base_url()
        self.messages: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="transcript"):
            yield Static(WELCOME_TEXT, id="welcome")
        yield Static("ready", id="status")
        yield Input(placeholder="Ask anything...", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one("#input", Input).value = ""
        self.run_worker(self.send_message(text), exclusive=False)

    async def send_message(self, text: str) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        status = self.query_one("#status", Static)
        input_widget = self.query_one("#input", Input)

        self.messages.append({"role": "user", "content": text})
        await transcript.mount(Static(line_user(text), classes="user-line"))

        answer_widget = Markdown("", classes="assistant-answer")
        await transcript.mount(answer_widget)
        answer_acc = ""

        reasoning_collapsible: Collapsible | None = None
        reasoning_widget: Static | None = None
        reasoning_acc = ""

        status.update("[magenta]thinking...[/magenta]")
        input_widget.disabled = True
        transcript.scroll_end(animate=False)

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/stream", json={"messages": self.messages}
                ) as resp:
                    resp.raise_for_status()
                    buffer = ""
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            raw_event, buffer = buffer.split("\n\n", 1)
                            raw_event = raw_event.strip()
                            if not raw_event.startswith("data:"):
                                continue
                            payload = raw_event[len("data:"):].strip()
                            if not payload:
                                continue
                            event_data = json.loads(payload)
                            event_type = event_data.get("type")

                            if event_type == "thinking":
                                if reasoning_collapsible is None:
                                    reasoning_widget = Static("", classes="reasoning-text")
                                    reasoning_collapsible = Collapsible(
                                        reasoning_widget, title="thinking", collapsed=False
                                    )
                                    await transcript.mount(reasoning_collapsible, before=answer_widget)
                                reasoning_acc += event_data["content"]
                                reasoning_widget.update(escape(reasoning_acc))
                                transcript.scroll_end(animate=False)

                            elif event_type == "delta":
                                answer_acc += event_data["content"]
                                answer_widget.update(answer_acc)
                                transcript.scroll_end(animate=False)

                            elif event_type == "tool_start":
                                name = event_data["name"]
                                status.update(f"[yellow]using {escape(name)}...[/yellow]")
                                await transcript.mount(Static(line_tool(f"{name}..."), classes="tool-line"))

                            elif event_type == "tool_end":
                                status.update("[magenta]thinking...[/magenta]")

                            elif event_type == "confirm_request":
                                status.update("[bold red]waiting for your approval...[/bold red]")
                                approved = await self.push_screen_wait(
                                    ConfirmScreen(event_data["tool"], event_data["preview"])
                                )
                                await client.post(
                                    f"{self.base_url}/chat/confirm",
                                    json={"id": event_data["id"], "approved": approved},
                                )
                                verdict = "approved" if approved else "denied"
                                await transcript.mount(
                                    Static(line_tool(f"{verdict}: {event_data['tool']}"), classes="tool-line")
                                )
                                status.update("[magenta]thinking...[/magenta]")

                            elif event_type == "done":
                                self.messages = event_data["messages"]

                            elif event_type == "error":
                                await transcript.mount(Static(line_error(event_data["message"])))

        except Exception as exc:
            await transcript.mount(Static(line_error(str(exc))))
        finally:
            if reasoning_collapsible is not None:
                reasoning_collapsible.collapsed = True
            status.update("[green]ready[/green]")
            input_widget.disabled = False
            input_widget.focus()
            transcript.scroll_end(animate=False)


if __name__ == "__main__":
    LocalAssistantApp().run()
