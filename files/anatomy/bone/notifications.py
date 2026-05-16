"""Notification ingestion — HMAC validator + delegate to clients/wing.py.

Anatomy A9 (2026-05-16). Mirrors events.py shape:

  - HMAC verification with the same WING_EVENTS_HMAC_SECRET (one shared
    secret per host; severity + intent live in the payload, not the
    transport).
  - Whitelist of valid severities + channels (re-checked client-side too).
  - validate_payload returns None on OK, error string on reject.
  - insert_notification delegates to clients/wing.py so the single seam
    rule (no sqlite3.connect against wing.db outside that module) holds.

Bone POST /api/v1/notifications calls verify_hmac + validate_payload, then
clients.wing.insert_notification. The /inbox presenter reads directly via
the Wing-side NotificationRepository — no Bone round-trip for reads.
"""

from __future__ import annotations

from typing import Any

from events import verify_hmac as _verify_hmac  # re-use the events HMAC helper
from clients import wing as _wing

# Re-export so main.py's import surface stays uniform with events.
verify_hmac = _verify_hmac

VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
VALID_CHANNELS = {"wing-inbox", "ntfy", "mail"}


def validate_payload(payload: dict[str, Any]) -> str | None:
    """Return error message if invalid, None if OK.

    Mandatory: severity, title. Optional: body, channels (default
    ["wing-inbox"]), target_actor_id (default "operator"), actor_id,
    actor_action_id, origin_plugin, origin_agent, source_event_id,
    metadata (dict).
    """
    severity = payload.get("severity")
    if not severity:
        return "missing required field: severity"
    if severity not in VALID_SEVERITIES:
        return f"invalid severity: {severity}"

    title = payload.get("title")
    if not title or not isinstance(title, str):
        return "missing or non-string required field: title"
    if len(title) > 500:
        return "title exceeds 500-char limit"

    body = payload.get("body")
    if body is not None and not isinstance(body, str):
        return "body must be a string"

    channels = payload.get("channels")
    if channels is not None:
        if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
            return "channels must be a list of strings"
        for ch in channels:
            if ch not in VALID_CHANNELS:
                return f"invalid channel: {ch}"

    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return "metadata must be an object"

    source_event_id = payload.get("source_event_id")
    if source_event_id is not None:
        try:
            int(source_event_id)
        except (TypeError, ValueError):
            return "source_event_id must be an integer"

    return None


def insert_notification(payload: dict[str, Any]) -> tuple[int, str]:
    """Insert into Wing's notifications table. Returns (id, uuid)."""
    return _wing.insert_notification(payload)
