"""Notification ingestion — HMAC validator + delegate to clients/wing.py.

Anatomy A9 (2026-05-16). Mirrors events.py shape:

  - HMAC verification with the same WING_EVENTS_HMAC_SECRET (one shared
    secret per host; severity + intent live in the payload, not the
    transport).
  - Whitelist of valid severities + channels (re-checked client-side too).
  - validate_payload returns None on OK, error string on reject.
  - insert_notification delegates to clients/wing.py so the single DB seam
    rule holds outside that module.

Bone POST /api/v1/notifications calls verify_hmac + validate_payload, then
clients.wing.insert_notification. The /inbox presenter reads directly via
the Wing-side NotificationRepository — no Bone round-trip for reads.
"""

from __future__ import annotations

import re
from typing import Any

from events import verify_hmac as _verify_hmac  # re-use the events HMAC helper
from clients import wing as _wing

# Re-export so main.py's import surface stays uniform with events.
verify_hmac = _verify_hmac

VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
VALID_CHANNELS = {"wing-inbox", "ntfy", "mail"}


def validate_payload(payload: dict[str, Any]) -> str | None:
    """Return error message if invalid, None if OK.

    Mandatory: severity AND (title OR template). Optional: body,
    context (dict, used with template), channels (default ["wing-inbox"]),
    target_actor_id (default "operator"), actor_id, actor_action_id,
    origin_plugin, origin_agent, source_event_id, metadata (dict).
    """
    severity = payload.get("severity")
    if not severity:
        return "missing required field: severity"
    if severity not in VALID_SEVERITIES:
        return f"invalid severity: {severity}"

    title = payload.get("title")
    template_name = payload.get("template")
    # 2026-05-17: emitters may send `template: <name>` + `context: <dict>`
    # INSTEAD of literal title+body. Bone resolves the template via the
    # plugin manifest's notification.templates map (rendered into the
    # routing sidecar by the wing-base aggregator). One of the two
    # must be present; both is allowed (literal wins).
    if not title and not template_name:
        return "missing required field: title (or template+context)"
    if title is not None and not isinstance(title, str):
        return "title must be a string"
    if title is not None and len(title) > 500:
        return "title exceeds 500-char limit"
    if template_name is not None:
        if not isinstance(template_name, str):
            return "template must be a string"
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,48}[a-z0-9]$", template_name):
            return f"template name {template_name!r} fails [a-z0-9][a-z0-9_-]+ pattern"
        context = payload.get("context")
        if context is not None and not isinstance(context, dict):
            return "context must be an object"

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

    # supersede_key (2026-08-23) — the emitter declaring "this message
    # REPLACES my earlier ones of the same class". Opt-in, because only the
    # sender can know: two gitleaks findings are two secrets, two prometheus
    # alerts two alarms, but two `os-resume` rows are one fact stated twice.
    #
    # Pattern-checked like `template`, and for the same reason: it becomes a
    # WHERE key over a shared table, so a loose value silently retires
    # another emitter's rows. Length-capped for the same reason.
    supersede_key = payload.get("supersede_key")
    if supersede_key is not None:
        if not isinstance(supersede_key, str):
            return "supersede_key must be a string"
        if not re.match(r"^[a-z0-9][a-z0-9_.:-]{0,62}[a-z0-9]$", supersede_key):
            return (f"supersede_key {supersede_key!r} fails "
                    "[a-z0-9][a-z0-9_.:-]+ pattern")

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
