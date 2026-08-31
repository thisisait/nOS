"""A ledger that cannot be read must not report that the model produced nothing.

MEASURED 2026-08-31, on the first model-authored proposal for a CRITICAL this
estate has ever had:

    08:58:33  loop_proposals row 24 written — rem:REM-212, session 8afe6278
    08:58:44  Bone seals an unrelated verdict (row 83)
    08:58:45  the proposer's session ends
    ~08:58:46 loop-propose.py reports:
              "no proposal citing rem:REM-212 appeared in the ledger
               (runner exit 0) — the run bought nothing"

The row was there the whole time. `_proposals_citing` caught
`sqlite3.OperationalError` and returned `[]` — a value that ALSO means "there
are no proposals". Its comment said `# no ledger yet — absence, not zero
proposals`, which names the distinction exactly and then returns a type that
cannot carry it.

WHICH OperationalError IS NOT ESTABLISHED, and this file will not pretend it
is. The first guess was lock contention with Bone's 08:58:44 verdict write —
wrong: wing.db runs in WAL, where readers do not block on writers. A read-only
URI connection to a WAL database can still fail on the -shm sidecar, and the
same shape appeared once more that morning (`unable to open database file`
from the pulse-runs source, on a database that opened fine a second later).
So: the CONFUSION is measured and fixed; the trigger is a live intermittent
that has now been given a name instead of a silent empty list. If it recurs,
`Unreadable` carries the sqlite message with it and the next reader will know
more than this one did.

WHAT IT COST. I read that line and concluded the run had bought nothing, wrote
it up, and went looking for why the proposer had failed. It had not failed. A
false negative here is expensive in a specific way: the next actor's obvious
move is to run the model AGAIN, paying a second time for work already on
record, and — because `content-fp-repeat` refuses a byte-identical patch — the
retry is then refused for the wrong reason.

TWO FIXES, and the second is the one that generalises. A 60s busy timeout
(the ledger's own default elsewhere) makes the common case simply wait. And
`Unreadable` is raised rather than returning a shape that reads as an answer,
so "I could not look" and "I looked and there was nothing" stop sharing an
exit code.

Retro-verified 2026-08-31 against a ledger locked by a live writer.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PROPOSE = REPO / "tools/loop-propose.py"


def _mod():
    spec = importlib.util.spec_from_file_location("loop_propose_unreadable", PROPOSE)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _ledger(path: pathlib.Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE loop_proposals (id INTEGER PRIMARY KEY, uuid TEXT, "
                 "weakness_id TEXT, session_uuid TEXT)")
    conn.execute("INSERT INTO loop_proposals VALUES (1,'u','rem:R-1','s')")
    conn.commit()
    conn.close()


def test_a_missing_ledger_raises_rather_than_reading_as_empty(tmp_path, monkeypatch) -> None:
    m = _mod()
    monkeypatch.setenv("WING_DB_PATH", str(tmp_path / "absent.db"))
    with pytest.raises(m.Unreadable):
        m._proposals_citing("rem:R-1")


def test_a_present_ledger_still_answers(tmp_path, monkeypatch) -> None:
    """The half that keeps the fix from being a brick: normal reads work."""
    db = tmp_path / "wing.db"
    _ledger(db)
    m = _mod()
    monkeypatch.setenv("WING_DB_PATH", str(db))
    rows = m._proposals_citing("rem:R-1")
    assert [r["id"] for r in rows] == [1]
    assert m._proposals_citing("rem:R-nothing") == [], (
        "a weakness with no proposals must still be an empty list — that is "
        "the case `Unreadable` exists to stop impersonating")


def test_an_unopenable_ledger_raises_rather_than_answering(tmp_path, monkeypatch) -> None:
    """The property, exercised through a failure that IS deterministic.

    Not lock contention: WAL readers do not block, so a test built on that
    would assert a mechanism this file has explicitly not established. An
    unreadable FILE reproduces the same OperationalError path every time, and
    the property under test — that the path raises instead of returning a
    shape that reads as an answer — is identical.
    """
    db = tmp_path / "wing.db"
    _ledger(db)
    db.chmod(0o000)
    m = _mod()
    monkeypatch.setenv("WING_DB_PATH", str(db))
    try:
        with pytest.raises(m.Unreadable) as exc:
            m._proposals_citing("rem:R-1")
    finally:
        db.chmod(0o644)
    assert "could not be read" in str(exc.value), (
        "the refusal does not carry sqlite's own message, so the next reader "
        "learns no more than this one did")


def test_the_runner_keeps_the_two_outcomes_apart() -> None:
    """`bought nothing` and `could not tell` must not share an exit code: the
    first invites a retry, the second invites a look."""
    src = PROPOSE.read_text(encoding="utf-8")
    body = src.split("def invoke(")[1].split("\ndef ")[0]
    assert "except Unreadable" in body, (
        "invoke() does not handle an unreadable ledger, so it falls through to "
        "the 'no proposal appeared' branch — the exact false negative measured")
    assert "return 2" in body, (
        "the unreadable path does not exit 2; exit 1 means the model bought "
        "nothing, which is a different fact about a different actor")


def test_schema_drift_raises_while_a_fresh_ledger_reads_as_empty(tmp_path, monkeypatch) -> None:
    """THE HOLE THE FIRST DRAFT LEFT, and the over-reach it led to.

    There are two OperationalError paths — connect and execute — and the first
    version of these tests exercised only connect, so restoring the old
    `return []` on the EXECUTE handler left every test green: a gate that
    cannot see the regression it was written for.

    Covering it the obvious way (a database with no `loop_proposals` table)
    then broke a deliberate decision this repo had already made and pinned in
    `test_a_run_that_proposed_nothing_is_not_success`: a FRESH estate has no
    loop_* tables until Bone creates them, and "no ledger yet" honestly means
    no proposals. So the split is by cause, not by path — absent table is an
    answer, a table that is there and unreadable is not.
    """
    m = _mod()

    fresh = tmp_path / "fresh.db"
    sqlite3.connect(fresh).close()
    monkeypatch.setenv("WING_DB_PATH", str(fresh))
    assert m._proposals_citing("rem:R-1") == [], (
        "a database with no ledger table must read as empty; a fresh host has "
        "one of these and it is not an error")

    drifted = tmp_path / "drifted.db"
    conn = sqlite3.connect(drifted)
    conn.execute("CREATE TABLE loop_proposals (id INTEGER PRIMARY KEY)")   # no session_uuid
    conn.commit()
    conn.close()
    monkeypatch.setenv("WING_DB_PATH", str(drifted))
    with pytest.raises(m.Unreadable) as exc:
        m._proposals_citing("rem:R-1")
    assert "no such column" in str(exc.value), (
        "a ledger whose shape has drifted answers as if it were empty, which "
        "is the false negative this file exists to stop")
