"""Every `install_flag` in state/manifest.yml resolves in a config layer.

MEASURED 2026-09-01: `install_redis` is named by state/manifest.yml, branched on
by roles/pazny.uptime_kuma/tasks/monitors.yml:302 and state/gdpr-erasure-map.yml
via `| default(false)`, and declared by NO config layer — the real toggle is
`redis_docker`. The Redis monitor and the Redis erasure pass have therefore
never run, at exit 0. A flag nothing declares is a branch nothing takes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from nos_identity import resolve_flag  # noqa: E402

#: The one undeclared flag, quarantined by name because the fix is a rename and
#: the DIRECTION is the operator's (declare `install_redis`, or point the row at
#: `redis_docker` — plan §6). Closing it must also empty this set.
PENDING_OPERATOR = {"install_redis"}


def test_every_manifest_install_flag_is_declared_somewhere():
    manifest = yaml.safe_load((REPO / "state" / "manifest.yml").read_text())
    undeclared = {
        s["install_flag"]
        for s in manifest["services"]
        if s.get("install_flag") and not resolve_flag(s["install_flag"])
    }
    assert undeclared == PENDING_OPERATOR, (
        f"undeclared: {sorted(undeclared)}; quarantined: {sorted(PENDING_OPERATOR)}"
    )
