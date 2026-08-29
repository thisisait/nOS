"""A row stranded by an emitter rename is still retirable — and ambiguity is not.

MEASURED 2026-08-29. 33 of 63 unread notifications sat under `os-resume`, the
origin_plugin `nos-notify.sh` hardcoded for EVERY caller until 2026-08-25. The
emitters were given their own names that day and each now declares a
`supersede_key`, so the restatement class exists and the sender opted into it —
but `bin/reconcile-inbox.php` keys the class on (origin_plugin, actor_id), which
the rename broke. `0 retirable`, for a backlog the mechanism was built for.

The bridge matches on the message SHAPE (title with digits stripped) instead,
and only ever as a fallback after the identity rule declines. It is evidence,
not a backfill: a later message saying the same thing, from an emitter that has
declared it repeats. Nothing is reclassified and no key is invented.

THE DANGEROUS HALF IS THE ONE TO GATE. Retiring the right row saves a click;
retiring the wrong one hides a fact the operator never saw. So the refusals get
the coverage: two declared emitters sending one shape is ambiguous and must be
refused, a shape with no declared successor must be refused, and the newest row
of a shape must never be retired — it is the current word.

Every case below runs the REAL script against a throwaway database built from
the committed schema artifact. No wing.db, no estate.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import sqlite3
import subprocess
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files/anatomy/wing/bin/reconcile-inbox.php"
SCHEMA = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")


def _ddl() -> str:
    m = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?notifications.*?\n\);",
                  SCHEMA.read_text(encoding="utf-8"), re.S)
    assert m, "no notifications DDL in the committed schema artifact"
    return m.group(0)


def _run(rows: list[dict]) -> str:
    """Build a wing.db holding exactly `rows`, run the reconciler, return stdout."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="reconcile"))
    # The script resolves wing.db from HOME, so the throwaway estate is a
    # throwaway HOME — nothing about the operator's own db is reachable.
    data = tmp / "wing/app/data"
    data.mkdir(parents=True)
    try:
        conn = sqlite3.connect(data / "wing.db")
        conn.executescript(_ddl())
        cols = ("uuid", "severity", "title", "body", "actor_id", "origin_plugin",
                "target_actor_id", "supersede_key", "created_at")
        conn.executemany(
            f"INSERT INTO notifications ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [tuple(r.get(c) for c in cols) for r in rows])
        conn.commit()
        conn.close()
        done = subprocess.run(["php", str(SCRIPT)], capture_output=True, text=True,
                              timeout=60, cwd=REPO / "files/anatomy/wing",
                              env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                                   "HOME": str(tmp), "WING_DATA_DIR": str(tmp)})
        assert done.returncode == 0, done.stderr[-400:]
        return done.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _row(uuid, title, when, *, origin="os-resume", key=None, actor="agent:x"):
    return {"uuid": uuid, "severity": "medium", "title": title, "body": "b",
            "actor_id": actor, "origin_plugin": origin, "target_actor_id": "operator",
            "supersede_key": key, "created_at": when}


def test_the_stranded_row_is_retired_by_its_renamed_successor() -> None:
    out = _run([
        _row("old-1", "S2 diff: 3 nights of agreement", "2026-08-01 05:00:00"),
        _row("new-1", "S2 diff: 9 nights of agreement", "2026-08-29 05:00:00",
             origin="cortex", key="cortex-corpus-diff"),
    ])
    assert "WOULD RETIRE  old-1" in out, out
    assert "retirable" in out


def test_two_declared_emitters_of_one_shape_are_refused() -> None:
    """The failure this bridge could cause, and the reason it asks for exactly
    one. Two senders using one title is not a class, it is a collision."""
    out = _run([
        _row("old-1", "Nightly report: 3 items", "2026-08-01 05:00:00"),
        _row("new-a", "Nightly report: 9 items", "2026-08-28 05:00:00",
             origin="alpha", actor="agent:a", key="alpha-nightly"),
        _row("new-b", "Nightly report: 4 items", "2026-08-29 05:00:00",
             origin="beta", actor="agent:b", key="beta-nightly"),
    ])
    assert "WOULD RETIRE  old-1" not in out, (
        "a row was retired on a shape two different declared emitters send; the "
        "successor named in its evidence may have nothing to do with it")
    assert "ambiguous" in out


def test_a_shape_with_no_declared_successor_is_left_alone() -> None:
    """No sender has opted in, so no class exists — the tool never runs ahead
    of the emitter, which is the rule the identity path already keeps."""
    out = _run([
        _row("old-1", "Something happened: 3", "2026-08-01 05:00:00"),
        _row("new-1", "Something happened: 9", "2026-08-29 05:00:00"),
    ])
    assert "WOULD RETIRE" not in out, out


def test_the_newest_row_of_a_shape_is_never_retired() -> None:
    out = _run([
        _row("old-1", "S2 diff: 3 nights", "2026-08-01 05:00:00"),
        _row("new-1", "S2 diff: 9 nights", "2026-08-29 05:00:00",
             origin="cortex", key="cortex-corpus-diff"),
    ])
    assert "WOULD RETIRE  new-1" not in out, (
        "the current word was retired — the operator would lose the only row "
        "that still says something true")


def test_it_writes_superseded_at_and_not_read_at() -> None:
    """`wing_inbox_read_at` is a claim about a HUMAN. Stamping it for a row
    nobody opened is the estate recording a decision the operator never made —
    the exact defect shape this codebase keeps paying for."""
    src = SCRIPT.read_text(encoding="utf-8")
    retire = src[src.index("'supersede'"):]
    assert "superseded_at" in retire and "superseded_by" in retire
    assert "SET wing_inbox_read_at" not in retire.split("verdict_restated")[0], (
        "the retire path stamps wing_inbox_read_at; retiring is not reading")
