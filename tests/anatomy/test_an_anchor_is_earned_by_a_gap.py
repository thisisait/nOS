"""A segment anchor is minted only where the chain was actually off.

MEASURED 2026-08-29, on this estate's live wing.db:

    99 segment anchors, and the newest was three hours old

An anchor is the audit chain's permission to resume at a `prev_hash` the
verifier cannot derive — the boundary of a window where the chain was off and
rows landed unsigned. `bin/backfill-event-chain.php` exists to record one after
an OFF→ON toggle, and its own docstring says so: *"MUST run after each flag
OFF->ON toggle"*.

`roles/pazny.wing/tasks/post.yml` runs it on EVERY converge where the chain is
enabled, and the only idempotence guard compared the recorded anchor with the
current tail — which has always moved since the last converge. So the estate
minted one authorised discontinuity per converge, none of them earned.

WHY IT MATTERS, stated exactly and no wider. Each anchor is a place the verifier
will accept a segment start it cannot otherwise justify. It is reachable only
after an unsigned row resets the segment, so this is not a free deletion of
history — but it converts "the chain broke here" into "the chain was allowed to
break here" at 99 points instead of the two or three the estate actually toggled
through, and the nightly verify reports `ok:true` either way. The chain's whole
value is that a discontinuity is remarkable.

Existing anchors are deliberately NOT removed: each one opens a segment already
signed under it, and deleting one would break verification of real history. The
fix is to stop minting.

Every case below runs the REAL script against a throwaway database.
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
SCRIPT = REPO / "files/anatomy/wing/bin/backfill-event-chain.php"
SCHEMA = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")


def _run(rows: list[tuple[int, str | None]]) -> tuple[str, set[str]]:
    """Build a db whose events are `(id, row_hash)`, run the script, report."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="anchor"))
    data = tmp / "data"
    data.mkdir(parents=True)
    try:
        conn = sqlite3.connect(data / "wing.db")
        body = SCHEMA.read_text(encoding="utf-8")
        for name in ("events", "audit_chain_meta"):
            m = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{name}\b.*?\n\);", body, re.S)
            assert m, f"{name} missing from the committed schema"
            conn.executescript(m.group(0))
        for rid, row_hash in rows:
            conn.execute(
                "INSERT INTO events (id, ts, run_id, type, prev_hash, row_hash) "
                "VALUES (?, '2026-08-29T00:00:00Z', 'r', 'task_ok', 'p', ?)",
                (rid, row_hash))
        conn.commit()
        conn.close()

        done = subprocess.run(
            ["php", str(SCRIPT), f"--data-dir={data}"], capture_output=True,
            text=True, timeout=60, cwd=SCRIPT.parent.parent)
        assert done.returncode == 0, done.stderr[-400:]

        conn = sqlite3.connect(data / "wing.db")
        got = {r[0] for r in conn.execute(
            "SELECT k FROM audit_chain_meta WHERE k LIKE 'chain_segment_anchor_%'")}
        conn.close()
        return done.stdout, got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_signed_tail_mints_nothing() -> None:
    """The every-converge case, and the whole defect. Chaining never stopped,
    so the next insert continues the segment and needs no authorisation."""
    out, anchors = _run([(1, "aa"), (2, "bb"), (3, "cc")])
    assert anchors == set(), (
        "an anchor was minted over a continuous chain — this is the path that "
        "produced 99 of them, one per converge")
    assert "no OFF->ON boundary" in out
    assert "now holds 0" in out, "post.yml keys `changed` on this phrase"


def test_an_unsigned_tail_mints_one() -> None:
    """The case the tool exists for: the chain was off, rows landed unsigned,
    and the next signed row will start a segment nothing else can justify."""
    out, anchors = _run([(1, "aa"), (2, "bb"), (3, None), (4, None)])
    assert anchors == {"chain_segment_anchor_bb"}, (
        f"expected the last SIGNED row's hash as the anchor, got {anchors}")


def test_an_empty_ledger_mints_the_genesis_anchor() -> None:
    """A fresh estate has no tail to anchor at; the verifier seeds GENESIS
    itself, and the recorded row is what makes the first segment legible."""
    _out, anchors = _run([])
    assert anchors == {"chain_segment_anchor_nos-audit-chain-genesis-v1"}


def test_a_second_run_over_the_same_gap_adds_nothing() -> None:
    """post.yml runs this every converge. Re-running over an unchanged
    chain-off window must not accumulate."""
    rows = [(1, "aa"), (2, None)]
    _out, first = _run(rows)
    _out2, again = _run(rows)
    assert first == again == {"chain_segment_anchor_aa"}


def test_the_operator_path_still_refuses_a_dirty_window() -> None:
    """`--acknowledge-gap-before` is the reviewed act for a gap found late, and
    its refusals are what stop it papering over tampering. Unchanged here, and
    pinned so this file's narrowing cannot be read as loosening that one."""
    # Counted, not quoted. The refusal messages are PHP concatenations split
    # across lines, so matching their prose fails on a reflow — and a gate that
    # fails on a reflow gets deleted. What is structural is that the path has
    # four separate refusals and a $refuse that exits non-zero.
    src = SCRIPT.read_text(encoding="utf-8")
    assert src.count("$refuse(") == 5, (
        f"{src.count('$refuse(')} refusals on the operator acknowledge path, "
        "was 5. It checks that the named row exists and is signed, that its "
        "prev_hash equals the last signed row before it, and that the window "
        "between is non-empty. Removing one is a decision about what may be "
        "authorised without review; adding one is fine — update this number "
        "and say which check you added.")
    assert re.search(r"\$refuse\s*=.*?exit\(2\)", src, re.S), (
        "the refusal no longer exits non-zero — an acknowledgement that did "
        "not happen would read as done")
