"""Wing client for Bone — centralized wing.db access.

Anatomy P0.1b (2026-05-04). Before this refactor Bone had two
independent direct-sqlite hits to wing.db:

  - events.py::insert_event()  — POST callback ingestion
  - main.py /api/v1/events     — paginated read for CLI users

Each instance opened its own connection, with its own copy of the
(eventually drift-prone) WING_DB_PATH default. The CI lint added in
this commit forbids ``sqlite3.connect.*wing\\.db`` anywhere outside
this module so future audit-trail / conductor / agent work can swap
the underlying transport (potentially to HTTP-via-Wing) by editing
ONE file.

Behaviour-equivalent to the pre-refactor state — same SQL, same
result shape, same WingDBNotReady semantics. Architecture change
(Bone → HTTP POST → Wing → SQLite) is a follow-up; scoped out of
P0.1b to keep the change reviewable.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


# Default fallback path mirrors files/anatomy/bone/events.py's default
# (post-A2/A3.5 layout). The WING_DB_PATH env var (set by bone.plist)
# wins at runtime; the default just keeps unit tests / local dev
# tolerable.
def _wing_db_path() -> Path:
    return Path(
        os.getenv(
            "WING_DB_PATH",
            os.path.expanduser("~/wing/app/data/wing.db"),
        )
    )


class WingDBNotReady(Exception):
    """Raised when Wing's SQLite DB hasn't been initialised yet.

    Mirrors the exception class the previous events.py exposed —
    callback plugin and route handlers already catch this to translate
    into HTTP 503 so transient pre-init states stay distinguishable
    from real INSERT failures.
    """


def _open() -> sqlite3.Connection:
    db = _wing_db_path()
    if not db.parent.exists() or not db.is_file():
        raise WingDBNotReady(
            f"Wing DB not initialised yet at {db}; "
            "pazny.wing/init-db.php hasn't run on this host"
        )
    return sqlite3.connect(str(db))


# ── Writes ────────────────────────────────────────────────────────────


def insert_event(payload: dict[str, Any]) -> int:
    """Insert an event row. Returns new row id.

    Column list mirrors files/anatomy/wing/db/schema-extensions.sql
    events table. Field-name mapping notes:

    - payload['result']  → result_json (JSON-encoded if dict)
    - payload['coexistence_service'] → coexist_svc column (verbose
      key name in payload, short column name in schema; intentional)
    - payload['patch_id'] → patch_id (P0.1 fix; was previously
      missing entirely)
    """
    with _open() as conn:
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
                payload.get("patch_id"),
                payload.get("coexistence_service"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


# ── Reads ─────────────────────────────────────────────────────────────


def query_events(
    *,
    run_id: str | None = None,
    type: str | None = None,
    since: str | None = None,
    migration_id: str | None = None,
    upgrade_id: str | None = None,
    patch_id: str | None = None,
    coexist_svc: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Paginated event query. Returns rows as dicts (cursor-style).

    Filters with None are skipped. ``limit`` is clamped to [1, 500].
    SQL is parameterized — every filter goes through ``?`` placeholders.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if type is not None:
        clauses.append("type = ?")
        params.append(type)
    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)
    if migration_id is not None:
        clauses.append("migration_id = ?")
        params.append(migration_id)
    if upgrade_id is not None:
        clauses.append("upgrade_id = ?")
        params.append(upgrade_id)
    if patch_id is not None:
        clauses.append("patch_id = ?")
        params.append(patch_id)
    if coexist_svc is not None:
        clauses.append("coexist_svc = ?")
        params.append(coexist_svc)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(500, int(limit)))

    with _open() as conn:
        cur = conn.execute(
            "SELECT id, ts, run_id, type, playbook, play, task, role, host, "
            "duration_ms, changed, result_json, migration_id, upgrade_id, "
            "patch_id, coexist_svc "
            f"FROM events {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
