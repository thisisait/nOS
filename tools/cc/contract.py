"""The one table shape every control-centre pane produces.

WHY A SHAPE AND NOT A WIDGET. Five TUI variants were built in parallel on
2026-08-29 and the useful thing they disagreed about was not the rendering — it
was whether a pane owns its data. Four re-implemented "run the reader, parse
JSON, cope with failure"; this module is that code once, so a pane is a
DECLARATION (columns, and how to turn the reader's JSON into rows) rather than
a program.

    {"ok": bool, "error": str|None, "columns": [str], "rows": [dict],
     "detail": {int: dict}, "meta": dict, "cmd": str}

`columns` + `rows` is deliberately the same pair nos-face's DataTable view model
takes (`files/anatomy/face/src/lib/tables/`), so a terminal theme for face and a
pane here can render from one payload. They are not yet ONE declaration — face's
generated seam is `state/genome/entity.schema.json` via `tools/genome-codegen.py`
and this is a hand-kept correspondence.

UNKNOWN IS NOT EMPTY. A reader that times out, exits nonzero, or prints
something that is not JSON returns `ok=False` with the reason — never zero rows.
The estate has paid for that distinction more than once, most expensively when a
health probe read an empty stack as `0/0 ready`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

# ponytail: the {columns, rows} correspondence with nos-face's table view model
# is hand-kept, not generated. Upgrade to a generated seam (the genome-codegen
# pattern) the day a THIRD renderer wants it — a second hand-copy is the
# trigger, and a third opinion about schemas is not.


def read_json(tool_relpath: str, args: tuple[str, ...] = (), timeout: int = 25):
    """Run a nOS reader with --json. Returns (data, reason); never raises."""
    tool = REPO / tool_relpath
    cmd = [sys.executable, str(tool), "--json", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=REPO)
    except Exception as e:  # noqa: BLE001 — every failure is the same answer
        return None, f"could not run {tool_relpath}: {e}"
    try:
        return json.loads(proc.stdout), None
    except Exception:
        snippet = (proc.stderr or proc.stdout or "").strip()[:200]
        return None, f"{tool_relpath}: non-JSON output (rc={proc.returncode}) {snippet}"


def table(pane, demo: bool = False) -> dict[str, Any]:
    """Drive one pane module to the shape above.

    A pane declares COLUMNS and build_rows(data), plus EITHER a READER (a
    `tools/*.py --json` script) OR its own fetch() returning (data, reason).
    """
    cmd = getattr(pane, "READER", None) or f"{pane.ID} (own source)"
    if demo:
        data, reason = pane.DEMO, None
    elif getattr(pane, "READER", None):
        data, reason = read_json(pane.READER, tuple(getattr(pane, "ARGS", ())))
    else:
        data, reason = pane.fetch()

    if reason is not None:
        return {"ok": False, "error": reason, "columns": pane.COLUMNS,
                "rows": [], "detail": {}, "meta": {}, "cmd": cmd}
    try:
        rows = pane.build_rows(data)
    except Exception as e:  # noqa: BLE001 — a shape change is UNKNOWN, not a crash
        return {"ok": False, "error": f"{pane.ID} could not read the reader's shape: {e}",
                "columns": pane.COLUMNS, "rows": [], "detail": {}, "meta": {}, "cmd": cmd}

    detail_fn = getattr(pane, "detail", lambda row, data: dict(row))
    meta_fn = getattr(pane, "meta", lambda data: {})
    return {
        "ok": True, "error": None, "columns": pane.COLUMNS, "rows": rows,
        "detail": {i: detail_fn(r, data) for i, r in enumerate(rows)},
        "meta": meta_fn(data), "cmd": cmd,
    }


def render_text(t: dict[str, Any], title: str = "") -> str:
    """Plain fixed-width rendering — what `tmux capture-pane -p` gives an LLM.

    The same rows the TUI shows. A pane whose text dump and screen could differ
    is two implementations of one answer.
    """
    out = [title] if title else []
    if not t["ok"]:
        out.append(f"UNKNOWN — {t['error']}")
        return "\n".join(out)
    if not t["rows"]:
        out.append("(0 rows — the reader answered, with nothing)")
        return "\n".join(out)

    cols = t["columns"]
    width = {c: min(48, max(len(c), *(len(str(r.get(c, ""))) for r in t["rows"])))
             for c in cols}
    # A pane is a quadrant, not a screen — and the estate's own data has a
    # `fix_version` holding 496 characters of prose. Shrink proportionally so
    # the row still lines up; wrapping destroys the only thing a table is for.
    budget = max(shutil.get_terminal_size(fallback=(120, 24)).columns
                 - 2 * max(len(cols) - 1, 0), 4 * len(cols))
    total = sum(width.values())
    if total > budget:
        width = {c: max(4, int(w * budget / total)) for c, w in width.items()}

    def cell(v, w):
        s = "" if v is None else str(v)
        return (s[: w - 1] + "…" if len(s) > w else s).ljust(w)

    head = "  ".join(cell(c.upper(), width[c]) for c in cols)
    out += [head, "-" * len(head)]
    out += ["  ".join(cell(r.get(c, ""), width[c]) for c in cols) for r in t["rows"]]
    return "\n".join(out)
