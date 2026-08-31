"""One pane, any content, switched from the palette.

Variant B's navigator shape — one subject full-height, Enter to open a row —
with the pane chosen at RUNTIME from a palette rather than baked into
`nos-cc.sh`'s layout. Every content is a module in `panes/`; see contract.py.

THE PALETTE IS TEXTUAL'S OWN. A hand-written one was built first and deleted:
Textual already binds Ctrl+P to a fuzzy-searching command palette, and taking
that key for a worse copy of it is the shape this codebase spends its afternoons
removing. Panes are contributed as a `Provider`, so they appear beside the
built-in commands (theme, quit) instead of replacing them.

It never writes. The pane RE-READS on a timer — `r` is the impatient version,
not the only one. That is the rule the control centre is built on and the first
version of this app broke it: a Textual pane that reads once and then sits there
is the stale-answer problem wearing a nicer face, and it looks healthy right up
until the reader stops answering.
"""

from __future__ import annotations

from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.widgets import DataTable, Footer, Header, Static

from . import contract
from . import panes as registry


class PaneProvider(Provider):
    """Every registered pane, offered to Ctrl+P."""

    def _hits(self):
        app = self.app
        for pid, mod in registry.all_panes().items():
            yield pid, mod, partial(app.show_pane, pid)

    async def discover(self) -> Hits:
        for pid, mod, run in self._hits():
            yield DiscoveryHit(mod.LABEL, run, help=mod.TITLE)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for pid, mod, run in self._hits():
            score = matcher.match(f"{mod.LABEL} {pid}")
            if score > 0:
                yield Hit(score, matcher.highlight(mod.LABEL), run, help=mod.TITLE)


class ControlCentreApp(App):
    CSS = """
    #status { height: 1; background: $panel; padding: 0 1; }
    #banner { height: auto; color: $warning; padding: 0 1; }
    #table  { height: 1fr; }
    #detail { height: 12; border-top: solid $primary; padding: 0 1; display: none; }
    #detail.shown { display: block; }
    /* A LIVE MICROPHONE IS NOT A TABLE CELL. When a pane reports that
       something is recording, it gets a full-width red bar that no amount of
       scrolling hides — the one state in this control centre that is about the
       room rather than about the estate. */
    #rec { height: 1; display: none; }
    #rec.on { display: block; background: $error; color: $text; text-style: bold; }
    """
    COMMANDS = App.COMMANDS | {PaneProvider}
    BINDINGS = [
        Binding("r", "reload", "Refresh"),
        Binding("enter", "drill", "Open row"),
        Binding("s", "pane_toggle", "Start/stop"),
        Binding("escape", "close", "Close detail"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, pane_id: str, demo: bool = False):
        super().__init__()
        self.panes = registry.all_panes()
        self.current = pane_id
        self.demo = demo
        self.table: dict = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status")
        yield Static("", id="banner")
        yield Static("", id="rec")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="detail")
        yield Footer()

    #: Seconds between re-reads. A pane may declare its own REFRESH; the
    #: default matches what nos-watch.sh used for the same readers.
    DEFAULT_REFRESH = 45

    def on_mount(self) -> None:
        self.action_reload()
        self.set_interval(self._interval(), self.action_reload)

    def _interval(self) -> float:
        return float(getattr(self.panes[self.current], "REFRESH", self.DEFAULT_REFRESH))

    # ── data ────────────────────────────────────────────────────────────────
    def show_pane(self, pane_id: str) -> None:
        self.current = pane_id
        self.action_reload()

    def action_reload(self) -> None:
        self.table = contract.table(self.panes[self.current], self.demo)
        self.draw()

    def draw(self) -> None:
        pane, t = self.panes[self.current], self.table
        dt = self.query_one("#table", DataTable)
        # KEEP THE CURSOR ACROSS A RE-READ. The caddy pane refreshes every five
        # seconds; a cursor that jumps back to row 0 on every tick makes a fast
        # pane unusable, which is the opposite of what the speed was for.
        keep = dt.cursor_row if dt.row_count else 0
        dt.clear(columns=True)
        for col in t["columns"]:
            dt.add_column(col.upper(), key=col)
        for row in t["rows"]:
            dt.add_row(*[str(row.get(c, "")) for c in t["columns"]])
        if dt.row_count:
            dt.move_cursor(row=min(keep, dt.row_count - 1))

        banner = self.query_one("#banner", Static)
        if not t["ok"]:
            banner.update(f"[b red]UNKNOWN[/] — {t['error']}")
        elif not t["rows"]:
            banner.update("[dim]0 rows — the reader answered, with nothing. "
                          "That is an answer, not a failure.[/]")
        else:
            banner.update("")

        meta = "  ".join(f"{k}={v}" for k, v in (t.get("meta") or {}).items()
                         if v not in (None, [], {}))
        self.query_one("#status", Static).update(
            f" [{'DEMO' if self.demo else 'LIVE'}] {pane.TITLE}   {meta}"
            f"   [dim]ctrl+p panes · enter row · r refresh[/]")
        self.title = f"nos-cc — {pane.LABEL}"

        rec = self.query_one("#rec", Static)
        if (t.get("meta") or {}).get("recording"):
            rec.update(" ● RECORDING — the microphone is open.  s = stop ")
            rec.add_class("on")
        else:
            rec.remove_class("on")

        # THE DETAIL PANEL SURVIVES A RE-READ, and on a five-second pane that is
        # the difference between reading a transcript and watching it vanish
        # mid-sentence. It re-renders for the row the cursor is still on.
        if self.query_one("#detail", Static).has_class("shown"):
            self.action_drill()

    # ── actions ─────────────────────────────────────────────────────────────
    def action_close(self) -> None:
        self.query_one("#detail", Static).remove_class("shown")
        self.query_one("#table", DataTable).focus()

    def on_data_table_row_selected(self, event) -> None:
        """Enter, from the table itself.

        The `enter` BINDING never fired: a focused DataTable with
        cursor_type="row" consumes the key and emits this message instead, so
        the App-level binding was dead the whole time the footer advertised it.
        """
        self.action_drill()

    def action_pane_toggle(self) -> None:
        """`s` — the one place a pane may ACT, and only over a live device.

        Every other pane in this control centre is a reader and stays one. A
        microphone is the exception the rule earns: requiring a converge to stop
        listening would mean the fastest way to stop being recorded is to edit
        YAML. The pane changes the RUNTIME only; the declaration in config.yml
        is untouched, so a converge re-asserts whatever the operator declared —
        and the reader says so rather than letting the two look identical.
        """
        pane = self.panes[self.current]
        toggle = getattr(pane, "toggle", None)
        if toggle is None:
            self.query_one("#banner", Static).update(
                "[dim]this pane has nothing to start or stop[/]")
            return
        try:
            said = toggle(self.table.get("raw") or {})
        except Exception as exc:                                # noqa: BLE001
            said = f"[b red]{type(exc).__name__}[/] {exc}"
        self.query_one("#banner", Static).update(said or "")
        self.action_reload()

    def action_drill(self) -> None:
        dt = self.query_one("#table", DataTable)
        if dt.cursor_row is None or not self.table["rows"]:
            return
        info = self.table["detail"].get(dt.cursor_row, {})
        body = "\n".join(f"[b]{k}:[/] {v}" for k, v in info.items()) or "(no detail)"
        detail = self.query_one("#detail", Static)
        detail.update(body)
        detail.add_class("shown")
