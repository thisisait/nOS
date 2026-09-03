"""Anatomy CI gate — every wing.db reader opens it through _ledger_open.

MEASURED 2026-08-20 and solved; BIT AGAIN 2026-09-03, because the fix covered
four readers and left the class open: a bare `mode=ro` open of the WAL-mode
ledger throws `unable to open database file` whenever Wing has checkpointed and
no writer holds the db (the sidecars are absent and ro may not create them).
agent-status.py died as an uncaught traceback the morning after a converge
restarted Wing — the failure is conditional on a condition nobody controls.

`tools/_ledger_open.py` is the one way in: mode=ro, then a labelled immutable
snapshot only when no live WAL, None = UNKNOWN. This gate closes the CLASS —
a new reader adopts the helper on the day it is written, or goes red here.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

#: A wing.db open that bypasses the helper. `immutable=1` on wing.db is also
#: refused — outside the helper it has no live-WAL guard and can read torn pages.
BARE = re.compile(r"sqlite3\.connect\([^)]*\?(mode=ro|immutable=1)")


def _offenders() -> list[str]:
    out = []
    for f in sorted((REPO / "tools").rglob("*.py")):
        if f.name == "_ledger_open.py":
            continue
        src = f.read_text(encoding="utf-8", errors="ignore")
        if "wing.db" not in src and "wing_db" not in src.lower():
            continue
        if "open_ledger_ro" in src or "open_or_raise" in src:
            continue
        if BARE.search(src):
            out.append(str(f.relative_to(REPO)))
    return out


def test_no_reader_opens_the_ledger_bare():
    bad = _offenders()
    assert not bad, (
        f"{len(bad)} reader(s) open wing.db without tools/_ledger_open.py:\n  "
        + "\n  ".join(bad)
        + "\n\nA bare mode=ro dies whenever Wing has checkpointed (2026-08-20, "
          "again 2026-09-03); a bare immutable=1 can read torn pages under a "
          "live writer. open_ledger_ro() is both, in the right order, with "
          "None = UNKNOWN")


def test_the_helper_itself_still_guards_the_snapshot():
    src = (REPO / "tools" / "_ledger_open.py").read_text(encoding="utf-8")
    assert "_live_wal" in src and "immutable=1" in src, (
        "the helper lost its live-WAL guard or its snapshot fallback — "
        "re-read its docstring before changing it")
