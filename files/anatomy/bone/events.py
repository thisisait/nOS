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
# Default fallback aligned with pazny.bone defaults (bone_wing_db_dir →
# wing_data_dir → ~/wing/app/data) post-A2/A3.5. The pre-A2 path
# ``~/projects/nOS/files/project-wing/data/wing.db`` was wiped when Wing
# source moved to files/anatomy/wing/ and Wing started running as host
# launchd. ``WING_DB_PATH`` env var (set by bone.plist) always wins at
# runtime — this is just a sane local-dev fallback.
WING_DB = Path(
    os.getenv(
        "WING_DB_PATH",
        os.path.expanduser("~/wing/app/data/wing.db"),
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
    # ── Track E: Tier-2 apps_runner deploy events ──────────────────────────
    "app.deployed",              # one event per onboarded apps/<name>.yml
                                 # manifest after compose up succeeds
    "app.removed",               # operator-triggered tear-down of a Tier-2 app
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
    # Accept BOTH `<hex>` and `sha256=<hex>` (GitHub-webhook convention used
    # by apps_runner / wing_telemetry). Strip the prefix if present so the
    # constant-time compare works on raw hex either way.
    sig_clean = sig_header[len("sha256="):] if sig_header.startswith("sha256=") else sig_header
    if not hmac.compare_digest(expected, sig_clean):
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
               migration_id, upgrade_id, patch_id, coexist_svc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                # Anatomy P0.1 fix (2026-05-04): patch_id was previously
                # missing from the column list entirely, so every patch
                # event correlation broke at the audit-trail seam. The
                # callback plugin sets _current_patch_id when an apply-
                # patches play tags an event, sends it as ``patch_id`` in
                # the payload; we now insert it.
                payload.get("patch_id"),
                # Note on naming: the callback sends the field as
                # ``coexistence_service`` (long form) but the column is
                # ``coexist_svc`` (schema-extensions.sql). The mapping
                # here is intentional — keep the verbose key in payloads
                # for readability, persist the short form for column
                # naming hygiene.
                payload.get("coexistence_service"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()
