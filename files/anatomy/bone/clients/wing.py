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
    - payload['source'] → source column (Anatomy P1, 2026-05-05).
      Closes CLAUDE.md "Wing /events table schema mismatch" tech debt:
      Bone's POST handler had been accepting `source` in JSON for ages
      but dropping it silently on INSERT. Free-text hint-level
      attribution ("callback" / "operator" / "agent:<name>") complements
      A10 actor_id below.
    - payload['actor_id'] / payload['actor_action_id'] / payload['acted_at']
      → A10 actor audit (2026-05-08). actor_id = Authentik client_id of
      the writer; actor_action_id = UUID grouping events of one logical
      action (e.g. agent_run_start + agent_run_end share one); acted_at =
      wall-clock time of the action (usually = ts). Pre-A10 callbacks
      leave these NULL — backwards compatible.
    """
    with _open() as conn:
        cur = conn.execute(
            """
            INSERT INTO events
              (ts, run_id, type, playbook, play, task, role, host,
               duration_ms, changed, result_json,
               migration_id, upgrade_id, patch_id, coexist_svc, source,
               actor_id, actor_action_id, acted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                payload.get("source"),
                payload.get("actor_id"),
                payload.get("actor_action_id"),
                payload.get("acted_at"),
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
    source: str | None = None,
    actor_id: str | None = None,
    actor_action_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Paginated event query. Returns rows as dicts (cursor-style).

    Filters with None are skipped. ``limit`` is clamped to [1, 500].
    SQL is parameterized — every filter goes through ``?`` placeholders.

    Free-text ``source`` filter (Anatomy P1) splits callback-driven from
    operator/agent events at the channel level. ``actor_id`` /
    ``actor_action_id`` (A10, 2026-05-08) provide cryptographic
    attribution: actor_id = Authentik client_id; actor_action_id = UUID
    grouping multi-event logical actions (e.g. agent_run_start +
    agent_run_end of one conductor pulse run share an actor_action_id).
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
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if actor_id is not None:
        clauses.append("actor_id = ?")
        params.append(actor_id)
    if actor_action_id is not None:
        clauses.append("actor_action_id = ?")
        params.append(actor_action_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(500, int(limit)))

    with _open() as conn:
        cur = conn.execute(
            "SELECT id, ts, run_id, type, playbook, play, task, role, host, "
            "duration_ms, changed, result_json, migration_id, upgrade_id, "
            "patch_id, coexist_svc, source, actor_id, actor_action_id, acted_at "
            f"FROM events {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── Notifications (Anatomy A9, 2026-05-16) ─────────────────────────────
#
# Mirrors the events shape: insert + query, single-seam access to
# wing.db.notifications. Bone /api/v1/notifications POST inserts here;
# the dispatch worker (Wing CLI bin/dispatch-notifications.php) does the
# per-channel flush directly against wing.db so there's no Bone round-trip
# for ntfy/mail delivery.


def _new_uuid4() -> str:
    """UUID4 — local helper so Bone's only crypto dep stays hmac/random."""
    import uuid
    return str(uuid.uuid4())


_VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_VALID_CHANNELS = {"wing-inbox", "ntfy", "mail"}


def _routing_path() -> Path:
    """Sidecar location for the plugin-aggregator-rendered routing map."""
    return _wing_db_path().parent / "notification-routing.json"


def _load_routing() -> dict[str, dict[str, list[str]]]:
    """Read the routing sidecar produced by wing-base post_compose.

    Returns a dict keyed by plugin slug; missing file = empty map (callers
    fall through to the default ["wing-inbox"] channel).
    """
    p = _routing_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data.get("entries") or {}


def _lookup_channels(origin_plugin: str | None, origin_agent: str | None, severity: str) -> list[str] | None:
    """Look up channel routing for (origin, severity). Returns None when
    no entry matches — caller falls back to ["wing-inbox"].
    """
    key = None
    if origin_plugin:
        # Match plugin.yml names like "gitleaks" or "wing-base"; aggregator
        # stores both `plugin_name` (e.g. "wing-base") and `slug`
        # (e.g. "wing") — match by whichever the caller passed.
        key = origin_plugin
    elif origin_agent:
        # Agent profiles' notification routing also lands in the routing
        # JSON; aggregator key is the agent name (e.g. "conductor").
        key = origin_agent
    if not key:
        return None
    entries = _load_routing()
    entry = entries.get(key) or entries.get(f"{key}-base")
    if not isinstance(entry, dict):
        return None
    field = f"on_{severity}"
    channels = entry.get(field)
    if not isinstance(channels, list):
        return None
    return [c for c in channels if isinstance(c, str)]


def insert_notification(payload: dict[str, Any]) -> tuple[int, str]:
    """Insert a notification row. Returns (id, uuid).

    Caller (Bone POST handler) does the HMAC + schema check; this is the
    last-defense whitelist (severity + channels). Title required, body
    optional.

    Channel resolution order:
      1. Explicit ``channels:`` in payload (always wins)
      2. Aggregator-rendered routing for the emitter's origin_plugin /
         origin_agent + severity (read from notification-routing.json)
      3. Default ["wing-inbox"]

    A10 actor audit: actor_id + actor_action_id are stored as-passed.
    source_event_id (soft FK events.id) lets /inbox deep-link the
    originating event row when a notification is event-derived.
    """
    severity = payload.get("severity") or "info"
    if severity not in _VALID_SEVERITIES:
        raise ValueError(f"invalid severity: {severity}")

    channels = payload.get("channels")
    if channels is None or (isinstance(channels, list) and not channels):
        # Aggregator-fallback: ask the routing sidecar before defaulting.
        routed = _lookup_channels(
            payload.get("origin_plugin"),
            payload.get("origin_agent"),
            severity,
        )
        channels = routed if routed else ["wing-inbox"]

    if not isinstance(channels, list) or not channels:
        channels = ["wing-inbox"]
    channels = list(dict.fromkeys(channels))  # de-dupe preserving order
    for ch in channels:
        if ch not in _VALID_CHANNELS:
            raise ValueError(f"invalid channel: {ch}")

    title = payload.get("title") or ""
    if not title:
        raise ValueError("title is required")

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")

    uuid_ = payload.get("uuid") or _new_uuid4()

    with _open() as conn:
        cur = conn.execute(
            """
            INSERT INTO notifications
              (uuid, severity, title, body,
               actor_id, actor_action_id, target_actor_id,
               origin_plugin, origin_agent, source_event_id,
               channels_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid_,
                severity,
                title,
                payload.get("body"),
                payload.get("actor_id"),
                payload.get("actor_action_id"),
                payload.get("target_actor_id") or "operator",
                payload.get("origin_plugin"),
                payload.get("origin_agent"),
                int(payload["source_event_id"]) if payload.get("source_event_id") is not None else None,
                json.dumps(channels),
                json.dumps(metadata),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0), uuid_


def query_notifications(
    *,
    target_actor_id: str = "operator",
    severity: str | None = None,
    unread_only: bool = False,
    since: str | None = None,
    actor_action_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Paginated notification query. Same shape as query_events.

    Filters with None/False are skipped. ``limit`` is clamped to [1, 500].
    Parameterized — all filters go through ``?`` placeholders.
    """
    clauses: list[str] = ["target_actor_id = ?"]
    params: list[Any] = [target_actor_id]

    if severity is not None:
        clauses.append("severity = ?")
        params.append(severity)
    if unread_only:
        clauses.append("wing_inbox_read_at IS NULL")
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(since)
    if actor_action_id is not None:
        clauses.append("actor_action_id = ?")
        params.append(actor_action_id)

    where = f"WHERE {' AND '.join(clauses)}"
    limit = max(1, min(500, int(limit)))

    with _open() as conn:
        cur = conn.execute(
            "SELECT id, uuid, severity, title, body, "
            "actor_id, actor_action_id, target_actor_id, "
            "origin_plugin, origin_agent, source_event_id, "
            "channels_json, wing_inbox_read_at, "
            "ntfy_dispatched_at, ntfy_error, "
            "mail_dispatched_at, mail_error, "
            "metadata_json, created_at "
            f"FROM notifications {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
        cols = [c[0] for c in cur.description]
        rows = []
        for raw in cur.fetchall():
            row = dict(zip(cols, raw))
            # Decode JSON columns for convenience.
            try:
                row["channels"] = json.loads(row.pop("channels_json") or "[]")
            except json.JSONDecodeError:
                row["channels"] = []
            try:
                row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                row["metadata"] = {}
            rows.append(row)
        return rows
