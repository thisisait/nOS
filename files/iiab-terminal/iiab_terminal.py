#!/usr/bin/env python3
# ==============================================================================
# IIAB Terminal — public TUI hub for SSH access to homelab services
# Runs as ForceCommand for the "home" user
# ==============================================================================

import asyncio
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

# ── Config (injected by Ansible template) ─────────────────────────────────────
CONFIG_PATH = os.environ.get(
    "IIAB_CONFIG", "/usr/local/etc/iiab-terminal/config.json"
)


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {
            "hostname": "homelab",
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "qwen3:14b",
            "kiwix_url": "http://127.0.0.1:8888",
            "services": [],
        }


CFG = load_config()

BANNER = r"""
  ___ ___   _   ___   _____                  _             _
 |_ _|_ _| /_\ | _ ) |_   _|__ _ _ _ __  (_)_ _  __ _| |
  | | | | / _ \| _ \   | |/ -_) '_| '  \ | | ' \/ _` | |
 |___|___/_/ \_\___/   |_|\___|_| |_|_|_||_|_||_\__,_|_|
"""


# ==============================================================================
# Screens
# ==============================================================================


class MainMenu(Screen):
    """Main menu with an overview of available services."""

    BINDINGS = [
        Binding("1", "push_screen('kiwix')", "Kiwix"),
        Binding("2", "push_screen('books')", "Library"),
        Binding("3", "push_screen('chat')", "AI Chat"),
        Binding("4", "push_screen('services')", "Services"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static(BANNER, classes="banner"),
            Static(
                f"Welcome to [bold]{CFG.get('hostname', 'homelab')}[/bold]! "
                "Select a service:",
                classes="welcome",
            ),
            ListView(
                ListItem(Label("[bold]1[/bold]  Kiwix — Offline Wikipedia, Gutenberg"), id="menu-kiwix"),
                ListItem(Label("[bold]2[/bold]  Library — E-book catalog"), id="menu-books"),
                ListItem(Label("[bold]3[/bold]  AI Chat — Local LLM"), id="menu-chat"),
                ListItem(Label("[bold]4[/bold]  Services — System overview"), id="menu-services"),
                id="main-list",
            ),
            id="main-container",
        )
        yield Footer()

    @on(ListView.Selected)
    def on_select(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if "kiwix" in item_id:
            self.app.push_screen("kiwix")
        elif "books" in item_id:
            self.app.push_screen("books")
        elif "chat" in item_id:
            self.app.push_screen("chat")
        elif "services" in item_id:
            self.app.push_screen("services")


class KiwixScreen(Screen):
    """Search and read Kiwix articles."""

    BINDINGS = [Binding("escape", "pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static("[bold]Kiwix — Offline Wikipedia[/bold]", classes="title"),
            Input(placeholder="Search for an article...", id="kiwix-search"),
            VerticalScroll(RichLog(id="kiwix-results", wrap=True, markup=True)),
            id="kiwix-container",
        )
        yield Footer()

    @on(Input.Submitted, "#kiwix-search")
    def on_search(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        log = self.query_one("#kiwix-results", RichLog)
        log.clear()
        log.write(f"Searching: [bold]{query}[/bold]...")
        self._search(query)

    @work(thread=True)
    def _search(self, query: str) -> None:
        log = self.query_one("#kiwix-results", RichLog)
        base = CFG.get("kiwix_url", "http://127.0.0.1:8888")
        url = f"{base}/search?pattern={urllib.request.quote(query)}&pageLength=10"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8")
                # Kiwix search API returns JSON or HTML depending on version
                try:
                    data = json.loads(text)
                    results = data if isinstance(data, list) else data.get("results", [])
                    if not results:
                        log.write("[dim]No results.[/dim]")
                        return
                    for i, r in enumerate(results[:10], 1):
                        title = r.get("title", r.get("name", "?"))
                        snippet = r.get("snippet", "")[:120]
                        path = r.get("path", r.get("url", ""))
                        log.write(f"\n[bold cyan]{i}.[/bold cyan] [bold]{title}[/bold]")
                        if snippet:
                            log.write(f"   {snippet}")
                        if path:
                            log.write(f"   [dim]{base}{path}[/dim]")
                except json.JSONDecodeError:
                    # HTML response — show as plain text summary
                    log.write(f"[dim]Kiwix returned HTML. Open in a browser: {base}[/dim]")
        except Exception as e:
            log.write(f"[red]Error: {e}[/red]")


class BooksScreen(Screen):
    """Browse the Calibre-Web catalog."""

    BINDINGS = [Binding("escape", "pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static("[bold]Library — Calibre-Web[/bold]", classes="title"),
            Input(placeholder="Search for a book or author...", id="books-search"),
            VerticalScroll(RichLog(id="books-results", wrap=True, markup=True)),
            id="books-container",
        )
        yield Footer()

    @on(Input.Submitted, "#books-search")
    def on_search(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        log = self.query_one("#books-results", RichLog)
        log.clear()
        log.write(f"Searching: [bold]{query}[/bold]...")
        self._search(query)

    @work(thread=True)
    def _search(self, query: str) -> None:
        log = self.query_one("#books-results", RichLog)
        books_url = CFG.get("calibreweb_url", "http://127.0.0.1:8083")
        log.write(f"\n[dim]Calibre-Web catalog: {books_url}[/dim]")
        log.write("[dim]To download, open the URL in a browser or use curl.[/dim]")
        log.write(f"\n  curl -o book.epub '{books_url}/download/<id>/epub'")


class ChatScreen(Screen):
    """Interactive chat with the local LLM (Ollama)."""

    BINDINGS = [Binding("escape", "pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static(
                f"[bold]AI Chat[/bold] — model: [cyan]{CFG.get('ollama_model', '?')}[/cyan]",
                classes="title",
            ),
            VerticalScroll(RichLog(id="chat-log", wrap=True, markup=True)),
            Input(placeholder="Type a message... (Esc = back)", id="chat-input"),
            id="chat-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write("[dim]Hi! I'm your local AI assistant. Ask me anything.[/dim]\n")

    @on(Input.Submitted, "#chat-input")
    def on_message(self, event: Input.Submitted) -> None:
        msg = event.value.strip()
        if not msg:
            return
        event.input.value = ""
        log = self.query_one("#chat-log", RichLog)
        log.write(f"\n[bold green]You:[/bold green] {msg}")
        log.write(f"[bold blue]AI:[/bold blue] ", end="")
        self._stream_response(msg)

    @work(thread=True)
    def _stream_response(self, prompt: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        base = CFG.get("ollama_url", "http://127.0.0.1:11434")
        model = CFG.get("ollama_model", "qwen3:14b")

        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": True,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{base}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                buffer = ""
                for line in resp:
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                        token = chunk.get("response", "")
                        buffer += token
                        # Flush on sentence boundaries or newlines
                        if any(c in token for c in ".!?\n") or len(buffer) > 80:
                            log.write(buffer, end="")
                            buffer = ""
                        if chunk.get("done"):
                            if buffer:
                                log.write(buffer)
                            log.write("")
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.write(f"\n[red]Error: {e}[/red]")


class ServicesScreen(Screen):
    """Overview of available homelab services."""

    BINDINGS = [Binding("escape", "pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static("[bold]Homelab services[/bold]", classes="title"),
            VerticalScroll(RichLog(id="svc-list", wrap=True, markup=True)),
            id="services-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#svc-list", RichLog)
        services = CFG.get("services", [])
        if not services:
            log.write("[dim]No services configured.[/dim]")
            return

        for svc in services:
            name = svc.get("name", "?")
            url = svc.get("url", "")
            desc = svc.get("description", "")
            port = svc.get("port", "")
            log.write(
                f"  [bold cyan]{name:20s}[/bold cyan] "
                f"[dim]{desc:30s}[/dim] "
                f"{url}"
            )
            if port:
                log.write(f"  {'':20s} curl http://127.0.0.1:{port}/")

        log.write(
            "\n[dim]For access from the terminal: "
            "curl -s http://127.0.0.1:<port>/ | head[/dim]"
        )


# ==============================================================================
# App
# ==============================================================================


class IIABTerminal(App):
    """IIAB Terminal — public SSH hub for the homelab."""

    CSS = """
    .banner {
        color: $accent;
        text-align: center;
        margin: 1 0;
    }
    .welcome {
        text-align: center;
        margin: 0 0 1 0;
    }
    .title {
        text-align: center;
        margin: 1 0;
        background: $primary-background;
        padding: 0 1;
    }
    #main-list {
        height: auto;
        max-height: 12;
        margin: 0 4;
    }
    #main-container, #kiwix-container, #books-container,
    #chat-container, #services-container {
        height: 100%;
    }
    #chat-log, #kiwix-results, #books-results, #svc-list {
        height: 1fr;
        margin: 0 1;
        border: solid $primary;
        padding: 1;
    }
    #chat-input, #kiwix-search, #books-search {
        margin: 1 1;
    }
    """

    TITLE = f"IIAB Terminal — {CFG.get('hostname', 'homelab')}"
    BINDINGS = [Binding("q", "quit", "Quit")]

    SCREENS = {
        "main": MainMenu,
        "kiwix": KiwixScreen,
        "books": BooksScreen,
        "chat": ChatScreen,
        "services": ServicesScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("main")


if __name__ == "__main__":
    app = IIABTerminal()
    app.run()
