"""Anatomy CI gate — every dashboard datasource uid is actually provisioned.

The veins fix (2026-05-30) closed a silent hole: the Wing SQLite datasource
(uid `wing_sqlite`) was referenced by the 99-playbook / 22-ai-agents dashboards
but never provisioned — its only declaration lived in the orphaned
`grafana-base/provisioning/datasources/all.yml.j2`, which the P1 (2026-05-05)
composition-plugin split stopped rendering. The dashboards rendered empty
against a fully-populated wing.db for weeks, and nothing caught it.

This gate pins the dashboard → datasource → provisioning chain:

  Every datasource uid referenced by a committed dashboard JSON MUST be
  declared by a datasource template that a composition plugin actually
  RENDERS (manifest has provisioning.datasource + a lifecycle render action).

A uid in the orphaned all.yml.j2 does NOT count — only rendered templates do,
which is exactly the distinction that would have failed before grafana-wing
existed.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"
DASHBOARDS_DIR = PLUGINS_ROOT / "grafana-base" / "provisioning" / "dashboards"

# Grafana built-in / synthetic datasource refs that are never provisioned by a
# file (handled by Grafana core) + template-variable refs ($-prefixed).
BUILTIN_UIDS = {
    "-- grafana --", "-- mixed --", "-- dashboard --", "grafana", "mixed",
    "dashboard",
}


def _referenced_uids() -> set[str]:
    """Literal datasource uids referenced across all dashboard JSONs."""
    uids: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "datasource":
                    if isinstance(val, str):
                        uids.add(val)
                    elif isinstance(val, dict) and isinstance(val.get("uid"), str):
                        uids.add(val["uid"])
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for jf in sorted(DASHBOARDS_DIR.glob("*.json")):
        walk(json.loads(jf.read_text()))

    # Drop built-ins and template-variable references ($foo / ${DS_FOO}).
    return {
        u for u in uids
        if u and not u.startswith("$") and u.lower() not in BUILTIN_UIDS
    }


def _provisioned_uids() -> set[str]:
    """uids declared by a datasource template that a plugin actually renders.

    A plugin "renders" its datasource when its manifest carries
    provisioning.datasource AND a lifecycle hook with `render: provisioning.datasource`.
    The orphaned grafana-base all.yml.j2 (no render action) is therefore
    excluded — which is the whole point of the gate.
    """
    uids: set[str] = set()
    for manifest_path in sorted(PLUGINS_ROOT.glob("*/plugin.yml")):
        manifest = yaml.safe_load(manifest_path.read_text()) or {}
        prov = (manifest.get("provisioning") or {}).get("datasource")
        if not prov:
            continue
        # Confirm a lifecycle hook renders it (not just a declared block).
        lifecycle = manifest.get("lifecycle") or {}
        renders = False
        for hook_actions in lifecycle.values():
            for action in hook_actions or []:
                if isinstance(action, dict) and action.get("render") == "provisioning.datasource":
                    renders = True
        if not renders:
            continue
        tmpl = manifest_path.parent / prov["template"]
        if not tmpl.exists():
            continue
        for line in tmpl.read_text().splitlines():
            m = re.match(r"\s*uid:\s*([^\s#]+)", line)
            if m:
                uids.add(m.group(1).strip().strip('"').strip("'"))
    return uids


def test_every_dashboard_datasource_uid_is_provisioned():
    referenced = _referenced_uids()
    provisioned = _provisioned_uids()
    missing = referenced - provisioned
    assert not missing, (
        f"dashboard datasource uid(s) referenced but NOT provisioned by any "
        f"rendering composition plugin: {sorted(missing)}.\n"
        f"referenced={sorted(referenced)}\nprovisioned={sorted(provisioned)}\n"
        f"Add a composition plugin under files/anatomy/plugins/ that renders a "
        f"datasource template declaring the missing uid (see grafana-wing)."
    )


def test_wing_sqlite_is_provisioned():
    """Regression pin for the specific orphan this gate was born from."""
    assert "wing_sqlite" in _provisioned_uids(), (
        "wing_sqlite datasource is not provisioned by any rendering plugin — "
        "the grafana-wing composition plugin should declare + render it."
    )
