"""Anatomy CI gate — breach-notification engine (gov-readiness P0 #4).

Two halves, both php-gated (skipif no php; GitHub pytest job has php 8.3,
Woodpecker python:3.13-slim self-skips):

  1. BreachDeadlines pure-math via a tiny php harness — the load-bearing
     correctness: Art-33 72h exact, timezone normalization (no host-offset
     skew), NIS2 1-month end-of-month clamp (no P1M overflow), risk/scope
     gating, and Art-34 REPORT-ONLY (overdueStages never returns it).
  2. bin/breach-scan.php against a seeded SQLite DB — escalation, the 3-channel
     critical insert, deterministic-uuid dedup, dry-run, and inertness.

(tests/wing-api/*.php is excluded from CI, so the deadline math is pinned HERE.)
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
BD = WING / "app" / "Model" / "BreachDeadlines.php"
SCAN = WING / "bin" / "breach-scan.php"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")

_HARNESS = (
    "<?php declare(strict_types=1);\n"
    "require getenv('BD');\n"
    "$in = json_decode(file_get_contents('php://stdin'), true);\n"
    "echo json_encode([\n"
    "  'compute' => \\App\\Model\\BreachDeadlines::compute($in['row']),\n"
    "  'overdue' => \\App\\Model\\BreachDeadlines::overdueStages($in['row'], $in['now'] ?? null),\n"
    "]);\n"
)


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    p = tmp_path_factory.mktemp("bd") / "probe.php"
    p.write_text(_HARNESS)
    return p


def _bd(harness, row, now=None):
    r = subprocess.run(
        ["php", str(harness)], capture_output=True, text=True,
        env={"BD": str(BD), "PATH": __import__("os").environ.get("PATH", "")},
        input=json.dumps({"row": row, "now": now}),
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── 1. deadline math ──────────────────────────────────────────────────────


def test_art33_not_applicable_when_no_risk(harness):
    c = _bd(harness, {"detected_at": "2026-01-15T00:00:00Z", "risk_level": "none", "status": "detected"})["compute"]
    assert c["art33"]["applicable"] is False
    assert c["art33"]["due_at"] is None


def test_art33_72h_exact(harness):
    c = _bd(harness, {"detected_at": "2026-01-15T00:00:00Z", "risk_level": "low", "status": "detected"})["compute"]
    assert c["art33"]["due_at"] == "2026-01-18T00:00:00+00:00"


def test_timezone_normalized_no_host_skew(harness):
    c = _bd(harness, {"detected_at": "2026-05-30T10:00:00+05:00", "risk_level": "low", "status": "detected"})["compute"]
    # +05:00 10:00 -> UTC 05:00, +72h -> 2026-06-02T05:00:00+00:00
    assert c["art33"]["due_at"] == "2026-06-02T05:00:00+00:00"


def test_nis2_one_month_end_of_month_clamp(harness):
    c = _bd(harness, {"detected_at": "2026-01-31T00:00:00Z", "risk_level": "none",
                      "status": "detected", "nis2_in_scope": 1})["compute"]
    assert c["nis2_final"]["due_at"] == "2026-02-28T00:00:00+00:00"  # NOT 2026-03-03
    assert c["nis2_24h"]["due_at"] == "2026-02-01T00:00:00+00:00"


def test_art34_report_only_never_escalated(harness):
    r = _bd(harness, {"detected_at": "2020-01-01T00:00:00Z", "aware_at": "2020-01-01T00:00:00Z",
                      "risk_level": "high", "status": "detected"}, now="2026-01-01T00:00:00Z")
    assert r["compute"]["art34"]["applicable"] is True
    assert "art34" not in r["overdue"], "Art-34 must never be escalated (report-only)"
    assert "art33" in r["overdue"], "an overdue reportable Art-33 must escalate"


def test_art34_waived_by_exception(harness):
    c = _bd(harness, {"detected_at": "2026-01-15T00:00:00Z", "risk_level": "high",
                      "status": "detected", "art34_exception": "encryption"})["compute"]
    assert c["art34"]["applicable"] is False


def test_nis2_out_of_scope_due_null(harness):
    c = _bd(harness, {"detected_at": "2026-01-15T00:00:00Z", "risk_level": "none",
                      "status": "detected", "nis2_in_scope": 0})["compute"]
    assert c["nis2_24h"]["due_at"] is None


# ── 2. breach-scan escalation ─────────────────────────────────────────────


def _seed(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE gdpr_breaches (
          id INTEGER PRIMARY KEY AUTOINCREMENT, detected_at TEXT, nature TEXT,
          status TEXT, risk_level TEXT, art33_due_at TEXT, notified_supervisor_at TEXT,
          nis2_early_warning_due_at TEXT, nis2_early_warning_done_at TEXT,
          nis2_notification_due_at TEXT, nis2_notification_done_at TEXT,
          nis2_final_report_due_at TEXT, nis2_final_report_done_at TEXT, art34_due_at TEXT,
          escalated_stages_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT);
        CREATE TABLE notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL UNIQUE,
          severity TEXT, title TEXT, body TEXT, origin_plugin TEXT, actor_id TEXT,
          target_actor_id TEXT, channels_json TEXT, metadata_json TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')));
    """)
    con.commit()
    return con


def _scan(db, *args):
    return subprocess.run(["php", str(SCAN), f"--db={db}", *args], capture_output=True, text=True)


def _ncount(con):
    return con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]


def _past(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _future(h):
    return (datetime.now(timezone.utc) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_art33_overdue_escalates_one_critical_three_channels(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    con.execute("INSERT INTO gdpr_breaches (detected_at,nature,status,risk_level,art33_due_at) VALUES (?,?,?,?,?)",
                (_past(80), "leak", "detected", "high", _past(80)))
    con.commit()
    r = _scan(db)
    assert r.returncode == 0, r.stderr
    assert _ncount(con) == 1
    sev, ch, uuid = con.execute("SELECT severity, channels_json, uuid FROM notifications").fetchone()
    assert sev == "critical"
    assert set(json.loads(ch)) == {"wing-inbox", "ntfy", "mail"}
    assert uuid == "breach-1-art33-overdue"
    # second run de-dups
    _scan(db)
    assert _ncount(con) == 1
    con.close()


def test_future_deadline_not_escalated(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    con.execute("INSERT INTO gdpr_breaches (detected_at,nature,status,risk_level,art33_due_at) VALUES (?,?,?,?,?)",
                (_future(10), "x", "detected", "high", _future(10)))
    con.commit()
    _scan(db)
    assert _ncount(con) == 0
    con.close()


def test_non_reportable_never_escalates(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    con.execute("INSERT INTO gdpr_breaches (detected_at,nature,status,risk_level,art33_due_at) VALUES (?,?,?,?,?)",
                (_past(80), "x", "non-reportable", "none", None))
    con.commit()
    _scan(db)
    assert _ncount(con) == 0
    con.close()


def test_nis2_24h_overdue_escalates(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    con.execute("INSERT INTO gdpr_breaches (detected_at,nature,status,risk_level,nis2_early_warning_due_at) "
                "VALUES (?,?,?,?,?)", (_past(30), "cyber", "detected", "medium", _past(30)))
    con.commit()
    _scan(db)
    assert _ncount(con) == 1
    assert con.execute("SELECT uuid FROM notifications").fetchone()[0] == "breach-1-nis2_24h-overdue"
    con.close()


def test_art34_never_escalated_even_when_due_past(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    con.execute("INSERT INTO gdpr_breaches (detected_at,nature,status,risk_level,art34_due_at) VALUES (?,?,?,?,?)",
                (_past(80), "x", "detected", "high", _past(80)))
    con.commit()
    _scan(db)
    assert _ncount(con) == 0, "no art34 escalation stage exists"
    con.close()


def test_dry_run_counts_without_inserting(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    con.execute("INSERT INTO gdpr_breaches (detected_at,nature,status,risk_level,art33_due_at) VALUES (?,?,?,?,?)",
                (_past(80), "x", "detected", "high", _past(80)))
    con.commit()
    r = _scan(db, "--dry-run")
    assert "1 overdue" in r.stdout
    assert _ncount(con) == 0
    con.close()


def test_empty_db_is_inert(tmp_path):
    db = tmp_path / "wing.db"
    con = _seed(db)
    r = _scan(db)
    assert "0 overdue" in r.stdout
    assert _ncount(con) == 0
    con.close()


def test_missing_db_exit_3(tmp_path):
    r = _scan(tmp_path / "nope.db")
    assert r.returncode == 3
