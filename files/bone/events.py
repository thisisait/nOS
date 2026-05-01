"""Event ingestion — HMAC validator + direct write to Wing's events.db.

Bone offers this as a convenience for the callback plugin (which prefers
HTTP → SQLite fallback). The plugin signs each request so that even if
Bone is behind nginx and exposed on a socket, a rogue script can't inject
fake events.
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

HMAC_SECRET = os.getenv("WING_EVENTS_HMAC_SECRET", "")
WING_DB = Path(
    os.getenv(
        "WING_DB_PATH",
        os.path.expanduser("~/projects/nOS/files/project-wing/data/wing.db"),
    )
)

VALID_TYPES = {
    "playbook_start", "playbook_end",
    "play_start", "play_end",
    "task_start", "task_ok", "task_changed", "task_failed",
    "task_skipped", "task_unreachable",
    "handler_start", "handler_ok",
    "migration_start", "migration_step_ok", "migration_step_failed", "migration_end",
    "upgrade_start", "upgrade_step_ok", "upgrade_end",
    "coexistence_provision", "coexistence_cutover", "coexistence_cleanup",
    # ── Track G/seed: agentic security scans (files/vuln-scan/scan-runner.sh) ─
    "scan.batch_started",        # batch picked + dispatching to LLM
    "scan.finding_recorded",     # one finding written to remediation-queue
    "scan.batch_done",           # state file updated, cycle counter checked
    # ── Track G/seed: programmatic security drift (hooks/playbook-end.d/) ────
    "security.drift.snapshot",   # 20-cve-drift-check.sh post-playbook snapshot
}


def verify_hmac(ts_header: str, sig_header: str, raw_body: bytes) -> tuple[bool, str]:
    """Returns (ok, error_reason). Constant-time compare."""
    if not HMAC_SECRET:
        return False, "HMAC secret not configured"
    if not ts_header or not sig_header:
        return False, "missing HMAC headers"
    if not ts_header.isdigit():
        return False, "invalid timestamp"
    drift = abs(int(time.time()) - int(ts_header))
    if drift > 300:
        return False, "timestamp out of window"

    message = f"{ts_header}.{raw_body.decode('utf-8', errors='replace')}"
    expected = hmac.new(
        HMAC_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        digestmod="sha256",
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        return False, "invalid signature"
    return True, ""


def validate_payload(payload: dict[str, Any]) -> str | None:
    for key in ("ts", "type", "run_id"):
        if not payload.get(key):
            return f"missing required field: {key}"
    if payload["type"] not in VALID_TYPES:
        return f"unknown event type: {payload['type']}"
    return None


class WingDBNotReady(Exception):
    """Raised when Wing's SQLite DB hasn't been initialised yet.

    Bone receives events before pazny.wing has run init-db.php on a fresh
    blank. Translate this into a 503 (transient) instead of 500
    (terminal) so the callback plugin keeps the events in its fallback
    queue and replays them on the next run.
    """


def insert_event(payload: dict[str, Any]) -> int:
    """Insert into Wing's events table. Returns new row id."""
    if not WING_DB.parent.exists() or not WING_DB.is_file():
        raise WingDBNotReady(
            f"Wing DB not initialised yet at {WING_DB}; "
            "pazny.wing/init-db.php hasn't run on this host"
        )
    conn = sqlite3.connect(str(WING_DB))
    try:
        cur = conn.execute(
            """
            INSERT INTO events
              (ts, run_id, type, playbook, play, task, role, host,
               duration_ms, changed, result_json,
               migration_id, upgrade_id, coexist_svc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["ts"],
                payload["run_id"],
                payload["type"],
                payload.get("playbook"),
                payload.get("play"),
                payload.get("task"),
                payload.get("role"),
                payload.get("host"),
                payload.get("duration_ms"),
                1 if payload.get("changed") else (0 if "changed" in payload else None),
                json.dumps(payload["result"]) if isinstance(payload.get("result"), dict) else None,
                payload.get("migration_id"),
                payload.get("upgrade_id"),
                payload.get("coexistence_service"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()
