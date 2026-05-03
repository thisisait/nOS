"""State endpoints — serve ~/.nos/state.yml as JSON.

Used by Wing's Api\\StatePresenter (proxies here) and by the
post-provision `state-report.yml` task that pushes state snapshots.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

STATE_PATH = Path(
    os.getenv("NOS_STATE_PATH", os.path.expanduser("~/.nos/state.yml"))
)


def read_state() -> dict[str, Any]:
    """Load ~/.nos/state.yml. Returns empty dict if absent."""
    if not STATE_PATH.is_file():
        return {}
    with STATE_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def get_services(state: dict[str, Any] | None = None) -> dict[str, Any]:
    s = state if state is not None else read_state()
    svcs = s.get("services")
    return svcs if isinstance(svcs, dict) else {}


def get_service(service_id: str) -> dict[str, Any] | None:
    services = get_services()
    svc = services.get(service_id)
    return svc if isinstance(svc, dict) else None


def write_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Atomically write `snapshot` to STATE_PATH (~/.nos/state.yml).

    Used by the POST /api/state endpoint that pazny.state_manager calls
    at end-of-run. The Ansible role already wrote the same file directly
    (it owns the canonical writer) — Bone re-writes anyway so:

      * fleet mode (future) where a central Bone aggregates state from
        many hosts has a single inbound endpoint to call,
      * write-through invalidates any in-process cache Bone may add
        later.

    Returns a small acknowledgement dict.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object (dict)")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(snapshot, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, STATE_PATH)
    try:
        STATE_PATH.chmod(0o600)
    except OSError:
        # Best-effort — not all filesystems honour chmod from a non-root daemon
        pass
    return {
        "accepted": True,
        "path": str(STATE_PATH),
        "services": len(snapshot.get("services", {}) or {}),
        "schema_version": snapshot.get("schema_version"),
    }
