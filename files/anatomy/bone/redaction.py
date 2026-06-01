"""PII redaction for embeddings payloads.

The qdrant-base plugin manifest declares ``bone_redaction_required: true``
("Bone MUST strip operator email before upsert"). Embeddings and their payloads
land in Qdrant, covered by two complementary GDPR controls:
  1. PREVENTION (this module) — strip direct identifiers (email) from an upsert
     payload BEFORE it leaves the host, so they never enter the vector store.
  2. REACH (Art. 17) — ``QdrantClient.delete_points(ids=|filter=)`` removes
     whatever vectors do land, on a per-subject erasure run.
Keeping identifiers out is the first line of defence; delete_points is the
remedy when something must be removed after the fact. (Earlier revisions of this
header claimed no points/delete existed — it does now; do not re-add that note.)

Default-on; set ``BONE_EMBED_REDACT=false`` to disable (debugging only).
"""

from __future__ import annotations

import os
import re
from typing import Any

# RFC-5322-lite — good enough to catch operator/user emails in free text such
# as agent prompt context or advisory summaries.
# Domain labels are dot-FREE char classes joined by explicit `\.` separators
# (not one `[...\.]+` class containing a dot) so there is no quantifier overlap
# to backtrack on — linear-time, no ReDoS (py/redos) on adversarial free text.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PLACEHOLDER = "[redacted-email]"


def redaction_enabled() -> bool:
    """True unless BONE_EMBED_REDACT is explicitly falsey."""
    return os.getenv("BONE_EMBED_REDACT", "true").strip().lower() not in {"0", "false", "no", ""}


def redact_text(value: str) -> str:
    return _EMAIL_RE.sub(_PLACEHOLDER, value)


def redact_value(value: Any) -> Any:
    """Recursively redact strings inside dicts/lists/tuples; scalars pass through."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_value(v) for v in value)
    return value


def redact_payload(payload: Any) -> Any:
    """Strip email addresses from an embeddings-upsert payload.

    Returns the input unchanged when redaction is disabled or the payload is
    ``None``. Walks nested dicts/lists; non-string scalars pass through.
    """
    if payload is None or not redaction_enabled():
        return payload
    return redact_value(payload)
