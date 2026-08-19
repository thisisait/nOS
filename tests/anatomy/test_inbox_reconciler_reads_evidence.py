"""The inbox reconciler marks a row read only on evidence it READ (2026-08-19).

MEASURED, the defect this pins: 69 unread CRITICAL/HIGH in the operator's
inbox were 23 distinct problems. Eight were pulse jobs green at that moment.
One incident sat there twice — the firing row AND the relay's own "RESOLVED:"
row, both unread. `markRead()` had exactly one caller: the operator's mouse.
A notification is an EVENT, the inbox is a STATE, and nothing reconciled them.

The reconciler (`files/anatomy/wing/bin/reconcile-inbox.php`) is allowed to
close a row only after reading the row's condition from the condition's OWN
source — pulse_runs, the alert relay's state, backup-status.json,
agent_questions — and it must record verbatim what it read. This gate runs the
real binary against a synthetic wing.db and refuses each of the ways such a
tool goes wrong:

  - marking on belief: a job that never ran, a still-red run, a still-open
    question, a still-firing alert must all leave the row unread;
  - absence read as resolution: a MISSING evidence source leaves the row
    unread and exits 2 (so the Pulse state-change alarm announces it);
  - writing without saying why: a marked row must carry `reconciled` evidence
    naming the source read;
  - touching what it cannot classify: an unknown title stays untouched;
  - acting without --apply: dry run is the default and writes nothing.

Every scenario runs the actual PHP entry point — no reimplementation of its
logic in Python, or the gate would verify the copy and not the tool.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "files/anatomy/wing/bin/reconcile-inbox.php"

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None,
    reason="php not in PATH — install via Homebrew or use the CI runner",
)


def _utc(offset_s: int = 0) -> str:
    """notifications.created_at shape: sqlite datetime('now'), UTC, no zone."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + offset_s))


def _iso(offset_s: int = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_s))


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            origin_plugin TEXT,
            target_actor_id TEXT NOT NULL DEFAULT 'operator',
            wing_inbox_read_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE pulse_jobs (
            id TEXT PRIMARY KEY,
            findings_exit_codes TEXT,
            removed_at TEXT
        );
        CREATE TABLE pulse_runs (
            run_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            fired_at TEXT NOT NULL,
            finished_at TEXT,
            exit_code INTEGER
        );
        CREATE TABLE agent_questions (
            uuid TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'open',
            answered_by TEXT,
            answered_at TEXT
        );
        """
    )
    return conn


def _notif(conn, uuid, title, *, origin=None, severity="high",
           metadata=None, created_offset=-3600) -> None:
    conn.execute(
        "INSERT INTO notifications (uuid, severity, title, origin_plugin,"
        " metadata_json, created_at) VALUES (?,?,?,?,?,?)",
        (uuid, severity, title, origin,
         json.dumps(metadata or {}), _utc(created_offset)),
    )
    conn.commit()


def _run(db: Path, tmp: Path, *args: str,
         relay_state: Path | None = None,
         backup_status: Path | None = None) -> subprocess.CompletedProcess:
    env = {
        "HOME": str(tmp),
        "PATH": "/usr/bin:/bin",
        "WING_DB_PATH": str(db),
        "ALERT_RELAY_STATE": str(relay_state or tmp / "absent-relay.json"),
        "BACKUP_STATUS_FILE": str(backup_status or tmp / "absent-backup.json"),
    }
    return subprocess.run(
        [shutil.which("php") or "php", str(CLI), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


def _row(db: Path, uuid: str) -> tuple[str | None, dict]:
    with sqlite3.connect(db) as conn:
        read_at, meta = conn.execute(
            "SELECT wing_inbox_read_at, metadata_json FROM notifications WHERE uuid=?",
            (uuid,),
        ).fetchone()
    return read_at, json.loads(meta)


# ── Pulse rows: pulse_runs is the source ─────────────────────────────────────

def test_green_run_after_the_row_closes_it_with_evidence(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO pulse_jobs (id) VALUES ('wing:audit-chain-verify')")
    conn.execute(
        "INSERT INTO pulse_runs VALUES ('run-green','wing:audit-chain-verify',?,?,0)",
        (_iso(-60), _iso(-30)),
    )
    _notif(conn, "n-fail", "Pulse job wing:audit-chain-verify failing (rc=3)")

    r = _run(db, tmp_path, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    read_at, meta = _row(db, "n-fail")
    assert read_at is not None
    assert meta["reconciled"]["read_from"] == "pulse_runs"
    assert meta["reconciled"]["run_id"] == "run-green"
    assert meta["reconciled"]["exit_code"] == 0


def test_a_job_that_never_ran_is_not_resolved(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO pulse_jobs (id) VALUES ('backup:backup-restore-drill')")
    _notif(conn, "n-norun", "Pulse job backup:backup-restore-drill failing (rc=1)")

    r = _run(db, tmp_path, "--apply")
    assert r.returncode == 0
    read_at, _ = _row(db, "n-norun")
    assert read_at is None, "absence of a run was read as resolution"
    assert "absence is not resolution" in r.stdout


def test_a_still_red_run_leaves_the_row_unread(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO pulse_jobs (id) VALUES ('keap:keap-features-sync')")
    conn.execute(
        "INSERT INTO pulse_runs VALUES ('run-red','keap:keap-features-sync',?,?,7)",
        (_iso(-60), _iso(-30)),
    )
    _notif(conn, "n-red", "Pulse job keap:keap-features-sync failing (rc=7)")

    _run(db, tmp_path, "--apply")
    read_at, _ = _row(db, "n-red")
    assert read_at is None


def test_declared_findings_exit_codes_count_as_green(tmp_path):
    # gitleaks exits 1 to say "ran correctly, found something" — declared in
    # pulse_jobs.findings_exit_codes, so the reconciler must read it, not
    # assume rc!=0 means broken.
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute(
        "INSERT INTO pulse_jobs (id, findings_exit_codes) VALUES ('gitleaks:nightly-scan','[1]')"
    )
    conn.execute(
        "INSERT INTO pulse_runs VALUES ('run-f','gitleaks:nightly-scan',?,?,1)",
        (_iso(-60), _iso(-30)),
    )
    _notif(conn, "n-findings", "Pulse job gitleaks:nightly-scan failing (rc=1)")

    _run(db, tmp_path, "--apply")
    read_at, meta = _row(db, "n-findings")
    assert read_at is not None
    assert meta["reconciled"]["exit_code"] == 1


def test_recovered_row_closes_on_its_own_green_run(tmp_path):
    # The recovered row is written moments AFTER its run finishes; the 120s
    # grace must accept the run that produced it as evidence.
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO pulse_jobs (id) VALUES ('wing:dispatch-notifications')")
    conn.execute(
        "INSERT INTO pulse_runs VALUES ('run-r','wing:dispatch-notifications',?,?,0)",
        (_iso(-95), _iso(-92)),
    )
    _notif(conn, "n-rec", "Pulse job wing:dispatch-notifications recovered (rc=0)",
           severity="info", created_offset=-90)

    _run(db, tmp_path, "--apply")
    read_at, _ = _row(db, "n-rec")
    assert read_at is not None


# ── Alert rows: the relay is the source ──────────────────────────────────────

def _alert_pair(conn):
    _notif(conn, "n-alert", "NosCriticalCveFoundCritical — studio.local",
           origin="prometheus-alert-relay", severity="critical",
           metadata={"fingerprint": "abcd1234abcd1234"}, created_offset=-7200)
    _notif(conn, "n-resolved", "RESOLVED: NosCriticalCveFoundCritical — studio.local",
           origin="prometheus-alert-relay", severity="info",
           metadata={"fingerprint": "abcd1234abcd1234", "resolved": True},
           created_offset=-3600)


def test_resolved_pair_closes_both_rows(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _alert_pair(conn)
    state = tmp_path / "prom-alerts-seen.json"
    state.write_text("{}")  # relay's live state: nothing firing

    r = _run(db, tmp_path, "--apply", relay_state=state)
    assert r.returncode == 0
    for uuid in ("n-alert", "n-resolved"):
        read_at, meta = _row(db, uuid)
        assert read_at is not None, f"{uuid} not closed"
        assert meta["reconciled"]["read_from"] == "alert-relay"
        assert meta["reconciled"]["fingerprint_in_state"] is False


def test_missing_relay_state_is_unreadable_not_resolved(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _alert_pair(conn)

    r = _run(db, tmp_path, "--apply")  # no relay state file at all
    assert r.returncode == 2, "an unreadable source must be announced, not absorbed"
    for uuid in ("n-alert", "n-resolved"):
        read_at, _ = _row(db, uuid)
        assert read_at is None
    assert "SOURCE UNREADABLE" in r.stdout


def test_fingerprint_still_in_relay_state_refuses(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _alert_pair(conn)
    state = tmp_path / "prom-alerts-seen.json"
    state.write_text(json.dumps({"abcd1234abcd1234": {"delivered_at": _iso(-60)}}))

    _run(db, tmp_path, "--apply", relay_state=state)
    read_at, _ = _row(db, "n-alert")
    assert read_at is None, "relay still lists the alert as firing"


def test_firing_row_without_a_resolved_row_stays(tmp_path):
    # Fingerprint absent from the state file is NOT enough on its own — the
    # relay must have SAID it resolved (its RESOLVED row is the delivery-
    # confirmed observation). A wiped state file must not close incidents.
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _notif(conn, "n-orphan", "NosWarningServiceDegraded — qdrant",
           origin="prometheus-alert-relay",
           metadata={"fingerprint": "feedfeedfeedfeed"})
    state = tmp_path / "prom-alerts-seen.json"
    state.write_text("{}")

    _run(db, tmp_path, "--apply", relay_state=state)
    read_at, _ = _row(db, "n-orphan")
    assert read_at is None


# ── Backup rows: backup-status.json is the source ────────────────────────────

def test_backup_row_closes_on_a_later_clean_run(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _notif(conn, "n-bak", "Backup FAILED for 2 source(s): wing, keap",
           origin="backup", created_offset=-86400)
    status = tmp_path / "backup-status.json"
    status.write_text(json.dumps({
        "last_run": int(time.time()) - 60,
        "in_progress": False,
        "sources": [{"name": "wing", "success": True},
                    {"name": "keap", "success": True}],
    }))

    _run(db, tmp_path, "--apply", backup_status=status)
    read_at, meta = _row(db, "n-bak")
    assert read_at is not None
    assert meta["reconciled"]["read_from"] == "backup-status.json"
    assert meta["reconciled"]["failed_count"] == 0


def test_backup_row_stays_while_a_source_still_fails(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _notif(conn, "n-bak2", "Backup FAILED for 1 source(s): keap",
           origin="backup", created_offset=-86400)
    status = tmp_path / "backup-status.json"
    status.write_text(json.dumps({
        "last_run": int(time.time()) - 60,
        "in_progress": False,
        "sources": [{"name": "keap", "success": False}],
    }))

    _run(db, tmp_path, "--apply", backup_status=status)
    read_at, _ = _row(db, "n-bak2")
    assert read_at is None


def test_missing_backup_status_is_unreadable(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _notif(conn, "n-bak3", "Backup FAILED for 1 source(s): keap", origin="backup")

    r = _run(db, tmp_path, "--apply")
    assert r.returncode == 2
    read_at, _ = _row(db, "n-bak3")
    assert read_at is None


# ── Agent questions: agent_questions is the source ───────────────────────────

def test_answered_question_closes_its_ask_row(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute(
        "INSERT INTO agent_questions VALUES ('q-1','answered','operator',?)",
        (_iso(-30),),
    )
    _notif(conn, "n-ask", "Agent asks: e2e-mock-agent", origin="agent-inbox",
           metadata={"question_uuid": "q-1"})

    _run(db, tmp_path, "--apply")
    read_at, meta = _row(db, "n-ask")
    assert read_at is not None
    assert meta["reconciled"]["read_from"] == "agent_questions"
    assert meta["reconciled"]["answered_by"] == "operator"


def test_open_question_keeps_its_ask_row_unread(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO agent_questions VALUES ('q-2','open',NULL,NULL)")
    _notif(conn, "n-ask2", "Agent asks: conductor", origin="agent-inbox",
           metadata={"question_uuid": "q-2"})

    _run(db, tmp_path, "--apply")
    read_at, _ = _row(db, "n-ask2")
    assert read_at is None


def test_a_missing_question_row_is_not_resolution(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _notif(conn, "n-ask3", "Agent asks: ghost", origin="agent-inbox",
           metadata={"question_uuid": "q-gone"})

    r = _run(db, tmp_path, "--apply")
    read_at, _ = _row(db, "n-ask3")
    assert read_at is None
    assert "absence is not resolution" in r.stdout


# ── Refusals that hold everywhere ────────────────────────────────────────────

def test_unclassified_rows_are_left_for_the_operator(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    _notif(conn, "n-x", "GDPR breach report overdue", origin="gdpr-breach")

    r = _run(db, tmp_path, "--apply")
    assert r.returncode == 0
    read_at, meta = _row(db, "n-x")
    assert read_at is None
    assert "reconciled" not in meta
    assert "UNCLASSIFIED" in r.stdout


def test_dry_run_is_the_default_and_writes_nothing(tmp_path):
    db = tmp_path / "wing.db"
    conn = _make_db(db)
    conn.execute("INSERT INTO pulse_jobs (id) VALUES ('wing:audit-chain-verify')")
    conn.execute(
        "INSERT INTO pulse_runs VALUES ('run-g','wing:audit-chain-verify',?,?,0)",
        (_iso(-60), _iso(-30)),
    )
    _notif(conn, "n-dry", "Pulse job wing:audit-chain-verify failing (rc=3)")

    r = _run(db, tmp_path)  # no --apply
    assert r.returncode == 0
    assert "WOULD MARK" in r.stdout
    read_at, meta = _row(db, "n-dry")
    assert read_at is None, "dry run wrote to the database"
    assert "reconciled" not in meta
