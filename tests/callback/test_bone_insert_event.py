"""Bone events.insert_event() round-trip tests.

Anatomy P0.1 (2026-05-04) — these tests guard the column list in Bone's
direct INSERT against wing.db so the regression that was uncovered today
(``patch_id`` silently dropped from the INSERT, breaking every
patch-correlated audit trail) cannot recur.

The tests use a tmp wing.db built from the canonical CREATE TABLE in
``files/anatomy/wing/db/schema-extensions.sql``. They patch the module's
``WING_DB`` to point at the tmp file.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BONE_DIR = REPO_ROOT / "files/anatomy/bone"
sys.path.insert(0, str(BONE_DIR))

# Bone's main.py boot-time auth assert is tolerant; just import events.
import events as bone_events  # noqa: E402


# Minimal events DDL extracted from schema-extensions.sql. Kept inline
# (instead of executing the .sql file) so the test stays focused on the
# columns that ``insert_event`` writes — the rest of the framework's
# tables aren't needed here.
EVENTS_DDL = """
CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    type          TEXT NOT NULL,
    playbook      TEXT,
    play          TEXT,
    task          TEXT,
    role          TEXT,
    host          TEXT,
    duration_ms   INTEGER,
    changed       INTEGER,
    result_json   TEXT,
    migration_id  TEXT,
    upgrade_id    TEXT,
    patch_id      TEXT,
    coexist_svc   TEXT,
    source        TEXT,                    -- Anatomy P1 (2026-05-05); attribution hint.
    actor_id          TEXT,                -- A10 (2026-05-08); cryptographic attribution.
    actor_action_id   TEXT,                -- A10; UUID grouping multi-event actions.
    acted_at          TEXT,                -- A10; wall-clock time of the action.
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@pytest.fixture
def wing_db(tmp_path, monkeypatch):
    db_path = tmp_path / "wing.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(EVENTS_DDL)
    conn.commit()
    conn.close()
    # Anatomy P0.1b (2026-05-04): patch the env var that
    # clients.wing._wing_db_path() reads on every connection. The
    # legacy events.WING_DB module-level constant is now just a
    # one-shot snapshot at import time — patching it has no effect on
    # subsequent lookups.
    monkeypatch.setenv("WING_DB_PATH", str(db_path))
    return db_path


def _payload(**overrides):
    base = {
        "ts": "2026-05-04T12:00:00Z",
        "run_id": "run_test-0001",
        "type": "task_ok",
    }
    base.update(overrides)
    return base


def test_minimal_insert_returns_row_id(wing_db):
    rid = bone_events.insert_event(_payload())
    assert rid > 0


def test_patch_id_round_trips(wing_db):
    """The bug we're guarding: callback sends patch_id, INSERT must persist it."""
    bone_events.insert_event(
        _payload(type="task_ok", patch_id="PATCH-042", task="apply-patch-042")
    )
    conn = sqlite3.connect(str(wing_db))
    try:
        rows = conn.execute(
            "SELECT patch_id, task FROM events WHERE patch_id IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("PATCH-042", "apply-patch-042")]


def test_coexist_svc_round_trips(wing_db):
    """coexistence_service in payload → coexist_svc column (verbose→short rename)."""
    bone_events.insert_event(
        _payload(type="coexistence_provision", coexistence_service="grafana")
    )
    conn = sqlite3.connect(str(wing_db))
    try:
        rows = conn.execute(
            "SELECT coexist_svc FROM events WHERE coexist_svc IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("grafana",)]


def test_full_payload_round_trips(wing_db):
    """All optional columns populated together."""
    bone_events.insert_event(
        _payload(
            type="task_changed",
            playbook="main.yml",
            play="apply",
            task="install foo",
            role="pazny.foo",
            host="nos-host",
            duration_ms=1234,
            changed=True,
            result={"ok": 1, "msg": "installed"},
            migration_id="M-001",
            upgrade_id="U-007",
            patch_id="PATCH-099",
            coexistence_service="bone-coexist-fixture",
        )
    )
    conn = sqlite3.connect(str(wing_db))
    try:
        row = conn.execute(
            "SELECT type, playbook, play, task, role, host, duration_ms, "
            "changed, result_json, migration_id, upgrade_id, patch_id, "
            "coexist_svc FROM events"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "task_changed"
    assert row[1] == "main.yml"
    assert row[6] == 1234
    assert row[7] == 1
    assert '"ok": 1' in row[8]
    assert row[9] == "M-001"
    assert row[10] == "U-007"
    assert row[11] == "PATCH-099"
    assert row[12] == "bone-coexist-fixture"


def test_missing_optional_columns_become_null(wing_db):
    bone_events.insert_event(_payload(type="playbook_start"))
    conn = sqlite3.connect(str(wing_db))
    try:
        row = conn.execute(
            "SELECT migration_id, upgrade_id, patch_id, coexist_svc FROM events"
        ).fetchone()
    finally:
        conn.close()
    assert row == (None, None, None, None)


def test_db_not_ready_raises(tmp_path, monkeypatch):
    """Wing DB never initialised → callback gets transient 503, not 500."""
    monkeypatch.setenv("WING_DB_PATH", str(tmp_path / "missing.db"))
    with pytest.raises(bone_events.WingDBNotReady):
        bone_events.insert_event(_payload())


def test_changed_field_normalisation(wing_db):
    """changed=True/False/missing → 1/0/NULL."""
    bone_events.insert_event(_payload(run_id="r1", changed=True))
    bone_events.insert_event(_payload(run_id="r2", changed=False))
    bone_events.insert_event(_payload(run_id="r3"))  # changed key absent
    conn = sqlite3.connect(str(wing_db))
    try:
        rows = sorted(
            conn.execute("SELECT run_id, changed FROM events").fetchall()
        )
    finally:
        conn.close()
    assert rows == [("r1", 1), ("r2", 0), ("r3", None)]


# ── P0.1b — query_events read path ─────────────────────────────────────


from clients import wing as bone_wing  # noqa: E402


def test_query_events_returns_inserted_rows(wing_db):
    """Round-trip: insert via insert_event, read back via query_events."""
    bone_events.insert_event(_payload(run_id="r1", type="task_ok"))
    bone_events.insert_event(_payload(run_id="r2", type="task_changed",
                                      patch_id="PATCH-1"))
    rows = bone_wing.query_events(limit=10)
    assert len(rows) == 2
    # Newest first (ORDER BY id DESC).
    assert rows[0]["run_id"] == "r2"
    assert rows[0]["patch_id"] == "PATCH-1"
    assert rows[1]["run_id"] == "r1"


def test_query_events_filters_by_run_id(wing_db):
    bone_events.insert_event(_payload(run_id="r-keep", type="task_ok"))
    bone_events.insert_event(_payload(run_id="r-drop", type="task_ok"))
    rows = bone_wing.query_events(run_id="r-keep")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "r-keep"


def test_query_events_filters_by_patch_id(wing_db):
    bone_events.insert_event(_payload(run_id="r1", type="task_ok",
                                      patch_id="PATCH-A"))
    bone_events.insert_event(_payload(run_id="r2", type="task_ok",
                                      patch_id="PATCH-B"))
    bone_events.insert_event(_payload(run_id="r3", type="task_ok"))
    rows = bone_wing.query_events(patch_id="PATCH-A")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "r1"


def test_query_events_limit_clamped(wing_db):
    """limit=0 → 1, limit=99999 → 500."""
    for i in range(10):
        bone_events.insert_event(_payload(run_id=f"r{i}"))
    assert len(bone_wing.query_events(limit=0)) == 1
    # Capped at 500 even if more rows exist (we only inserted 10 here).
    assert len(bone_wing.query_events(limit=99999)) == 10


def test_query_events_raises_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("WING_DB_PATH", str(tmp_path / "missing.db"))
    with pytest.raises(bone_wing.WingDBNotReady):
        bone_wing.query_events()


# ── P0.1b — CI lint: forbid sqlite3 hits to wing.db outside clients/wing.py ──


def test_no_direct_sqlite3_to_wing_db_outside_clients_wing(tmp_path):
    """Architectural invariant: only files/anatomy/bone/clients/wing.py
    may open wing.db directly. If a future refactor switches the
    transport to HTTP-via-Wing, the seam stays single-file."""
    import re
    bone_dir = REPO_ROOT / "files/anatomy/bone"
    pattern = re.compile(r'sqlite3\.connect\b.*wing\.db', re.IGNORECASE)
    offenders = []
    for f in bone_dir.rglob("*.py"):
        # Allow the centralized client to do it — that's its job.
        if f.relative_to(bone_dir).as_posix() == "clients/wing.py":
            continue
        # Skip generated / cache files.
        if "__pycache__" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{f}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Direct sqlite3 access to wing.db detected outside "
        "files/anatomy/bone/clients/wing.py:\n  " + "\n  ".join(offenders)
        + "\n\nMove the access into clients/wing.py and import it."
    )
