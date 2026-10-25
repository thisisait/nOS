"""CI runs the Node major the host pins, so a lockfile written here installs there.

2026-10-24: the host moved to node 24 (npm 11, node_nvm_version 24.22.1) while CI
stayed on node 22 (npm 10). npm 11 prunes nested @esbuild/* entries that npm 10
requires, so the cortex lock rewritten on the host made `npm ci` refuse on CI
("Missing: esbuild@0.28.2"), the second time (bf840bf56, 2026-10-09). Shown:
`npx npm@10 ci --dry-run` red, `npm ci --dry-run` (npm 11) green on the same lock.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402


def test_every_ci_node_is_the_pinned_major():
    pin = ni.resolve_flag("node_nvm_version", ni.default_layers())[-1][1]
    major = pin.split(".")[0]
    found = []
    for wf in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        found += [(wf.name, v) for v in re.findall(r"node-version:\s*['\"]?([0-9.]+)", wf.read_text(encoding="utf-8"))]
    assert found, "no node-version in any workflow"
    off = [(f, v) for f, v in found if v.split(".")[0] != major]
    assert not off, f"CI node majors {off} != host pin {pin} (node_nvm_version)"
