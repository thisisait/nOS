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
