"""tools/efferent.py list — the commands handed to you, until a reader saw them run.

A row is data any table writer controls. efferent.py already escapes every
unprintable byte; this pane also escapes Rich markup, because app.py hands a str
cell to Textual and `[link=…]` in a row would otherwise be obeyed. It never
offers the raw bytes: `copy:` names the command that prints them.
"""
from rich.markup import escape

ID, LABEL, TITLE = "efferent", "Efferent queue", "commands handed to you, closed only when seen"
READER = "tools/efferent.py"
ARGS = ("list",)
REFRESH = 30
COLUMNS = ["slug", "status", "machine", "app", "why"]
DEMO = {"ok": True, "unknown": None, "rows": [
    {"slug": "e1", "status": "open", "machine": "studio", "app": "shell",
     "why": "push the row branch [link=https://x]not a link[/link]",
     "command": "tools/nos-push origin feat/x", "reader": "ls-remote-has",
     "reader_args": "origin feat/x 0123abc", "clean": True, "problem": ""}]}


def build_rows(data):
    if not data.get("ok"):
        raise ValueError(data.get("unknown") or "efferent.py answered not ok")
    return [{c: escape(str(r.get(c, ""))) for c in COLUMNS} for r in data["rows"]]


def _src(row, data):
    return next((r for r in data["rows"] if escape(str(r.get("slug", ""))) == row["slug"]), {})


def detail(row, data):
    r = _src(row, data)
    out = {k: escape(str(r.get(k) or "")) for k in ("command", "reader", "reader_args", "seen_at")}
    out["copy"] = escape(f"tools/efferent.py show {r.get('slug', '')} | pbcopy")
    if not r.get("clean", True):
        out["problem"] = escape(str(r.get("problem", ""))) + " — show refuses to print it raw"
    return out


def meta(data):
    rows = data.get("rows") or []
    return {"open": sum(r.get("status") in ("open", "copied") for r in rows)}
