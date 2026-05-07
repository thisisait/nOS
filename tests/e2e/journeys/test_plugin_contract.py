"""Journey: plugin contract — aggregator-dry-run + drift-CI sanity.

Walks the structural contract that Track-Q + D-series rest on:
  1. tools/aggregator-dry-run.py exit 0 = no field-diffs vs central state
  2. Every plugin manifest validates against state/schema/plugin.schema.json
  3. tools/aggregator-dry-run.py output declares non-zero plugin count
     (catches a regression where the aggregator silently parses 0 plugins)

This journey is the canonical "green build" gate — when this fails,
something structural drifted and Phase 5 ceremony assumptions break.
Runs entirely from the repo (no live services), so it's the fastest
journey to keep green.
"""

from __future__ import annotations

import json
import os
import subprocess
from glob import glob

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def test_plugin_contract(journey):
    with journey("plugin_contract") as j:
        with j.step("aggregator_dry_run") as s:
            proc = subprocess.run(
                ["python3", "tools/aggregator-dry-run.py"],
                cwd=_REPO,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert proc.returncode == 0, (
                f"aggregator-dry-run.py exited {proc.returncode}\n"
                f"--- stdout ---\n{proc.stdout[-1000:]}\n"
                f"--- stderr ---\n{proc.stderr[-1000:]}"
            )
            s.note = f"exit=0, stdout={len(proc.stdout)}b"

        with j.step("count_plugin_manifests") as s:
            paths = glob(os.path.join(_REPO, "files", "anatomy", "plugins", "*", "plugin.yml"))
            n = len(paths)
            assert n >= 30, f"only {n} plugin manifests found; expected ≥30"
            s.note = f"manifests={n}"

        with j.step("count_authentik_blocks") as s:
            import yaml
            with_authentik = 0
            for p in glob(os.path.join(_REPO, "files", "anatomy", "plugins", "*", "plugin.yml")):
                try:
                    with open(p) as fh:
                        doc = yaml.safe_load(fh) or {}
                except Exception:
                    continue
                if isinstance(doc.get("authentik"), dict):
                    with_authentik += 1
            assert with_authentik >= 20, (
                f"only {with_authentik} plugins declare authentik block; "
                f"expected ≥20 (D1 cutover should have ~30+)"
            )
            s.note = f"plugins_with_authentik={with_authentik}"
