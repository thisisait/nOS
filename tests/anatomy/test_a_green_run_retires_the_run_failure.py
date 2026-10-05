"""A playbook-run failure is answered by the NEXT run's outcome (2026-10-05).

MEASURED: 11 unread HIGH "Playbook run failed: 1 failed, 0 unreachable" rows
(2026-09-30 … 10-04), every one followed by green converges, and red-status
called them "no re-checkable claim (UNKNOWN)" for ever: the emitter
(callback_plugins/wing_telemetry.py) sent no supersede_key and no green word.

Now each run's outcome carries `playbook-run:<host>` (pinned in
tests/callback/test_failure_notification.py). This gate pins the two readers:
the reconciler retires the keyless backlog once a later outcome exists, and
red-status reads the same evidence. Both run the real artifacts.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import sqlite3
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "files/anatomy/wing/db/schema-extensions.sql"
RECONCILER = REPO / "files/anatomy/wing/bin/reconcile-inbox.php"
RED = REPO / "tools/red-status.py"

FAIL = "Playbook run failed: 1 failed, 0 unreachable"


def _db(tmp_path, rows):
    """rows = (uuid, severity, title, origin_plugin, supersede_key, created_at)."""
    db = tmp_path / "wing.db"
    src = SCHEMA.read_text(encoding="utf-8")
    start = src.index("CREATE TABLE IF NOT EXISTS notifications")
    end = src.index("CREATE INDEX IF NOT EXISTS idx_notifications_created_at")
    conn = sqlite3.connect(db)
    conn.executescript(src[start:end])
    for uuid, sev, title, origin, key, created in rows:
        conn.execute(
            "INSERT INTO notifications (uuid, severity, title, origin_plugin, actor_id,"
            " supersede_key, metadata_json, created_at) VALUES (?,?,?,?,'operator',?,?,?)",
            (uuid, sev, title, origin, key, '{"recap": {"failed": 1}}', created))
    conn.commit()
    conn.close()
    return db


LEGACY = [  # what the live inbox holds: no origin, no key
    ("old-1", "high", FAIL, None, None, "2026-09-30 18:11:52"),
    ("old-2", "high", FAIL, None, None, "2026-10-04 12:29:11"),
]
GREEN = ("ok-1", "info", "Playbook run OK: 1493 ok", "playbook-run",
         "playbook-run:host", "2026-10-04 17:00:06")


def _state(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return {r["uuid"]: dict(r) for r in conn.execute("SELECT * FROM notifications")}
    finally:
        conn.close()


@pytest.mark.skipif(shutil.which("php") is None, reason="php absent")
def test_the_reconciler_retires_the_backlog_on_a_later_outcome(tmp_path):
    db = _db(tmp_path, LEGACY + [GREEN])
    out = subprocess.run(["php", str(RECONCILER), "--apply"], capture_output=True,
                         text=True, timeout=120, env=dict(os.environ, WING_DB_PATH=str(db)))
    assert out.returncode in (0, 2), out.stderr[-400:]
    rows = _state(db)
    for old in ("old-1", "old-2"):
        assert rows[old]["superseded_by"] == "ok-1", out.stdout[-800:]
        assert rows[old]["wing_inbox_read_at"] is None, "nobody read it"
    assert not rows["ok-1"]["superseded_at"]


@pytest.mark.skipif(shutil.which("php") is None, reason="php absent")
def test_without_a_later_outcome_the_failure_stays(tmp_path):
    db = _db(tmp_path, LEGACY)
    subprocess.run(["php", str(RECONCILER), "--apply"], capture_output=True,
                   text=True, timeout=120, env=dict(os.environ, WING_DB_PATH=str(db)))
    assert not any(r["superseded_at"] for r in _state(db).values())


def _red():
    spec = importlib.util.spec_from_file_location("red_status_run", RED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_red_status_decides_a_run_failure_against_later_runs(tmp_path):
    mod = _red()
    db = _db(tmp_path, LEGACY + [GREEN])
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    inbox = mod.unread_inbox(conn)
    assert inbox["critical_or_high_unresolvable"] == 0, inbox
    assert inbox["critical_or_high_provably_stale"] == 2, inbox

    (tmp_path / "x").mkdir()
    db2 = _db(tmp_path / "x", LEGACY)
    conn2 = sqlite3.connect(f"file:{db2}?mode=ro", uri=True)
    conn2.row_factory = sqlite3.Row
    inbox2 = mod.unread_inbox(conn2)
    # No green row after them is not proof of red (scoped runs send none).
    assert inbox2["critical_or_high_unresolvable"] == 2, inbox2
    assert inbox2["critical_or_high_provably_stale"] == 0, inbox2


# CodeRabbit PR #36: a keyed failure is answered only by ITS host's next run.
# Host B's green says nothing about host A; the keyless backlog (no host) is
# the one separately named exception, pinned above.
FAIL_A = ("fail-a", "high", FAIL, "playbook-run", "playbook-run:a", "2026-10-05 08:00:00")
GREEN_B = ("ok-b", "info", "Playbook run OK: 9 ok", "playbook-run",
           "playbook-run:b", "2026-10-05 09:00:00")
GREEN_A = ("ok-a", "info", "Playbook run OK: 9 ok", "playbook-run",
           "playbook-run:a", "2026-10-05 10:00:00")


@pytest.mark.skipif(shutil.which("php") is None, reason="php absent")
@pytest.mark.parametrize("rows, retired", [([FAIL_A, GREEN_B], None),
                                           ([FAIL_A, GREEN_B, GREEN_A], "ok-a")])
def test_the_reconciler_retires_a_keyed_failure_only_by_its_host(tmp_path, rows, retired):
    db = _db(tmp_path, rows)
    out = subprocess.run(["php", str(RECONCILER), "--apply"], capture_output=True,
                         text=True, timeout=120, env=dict(os.environ, WING_DB_PATH=str(db)))
    assert out.returncode in (0, 2), out.stderr[-400:]
    assert _state(db)["fail-a"]["superseded_by"] == retired, out.stdout[-800:]


@pytest.mark.parametrize("rows, stale", [([FAIL_A, GREEN_B], 0),
                                         ([FAIL_A, GREEN_B, GREEN_A], 1)])
def test_red_status_decides_a_keyed_failure_only_by_its_host(tmp_path, rows, stale):
    db = _db(tmp_path, rows)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    inbox = _red().unread_inbox(conn)
    assert inbox["critical_or_high_provably_stale"] == stale, inbox
    assert inbox["critical_or_high_unresolvable"] == 1 - stale, inbox
