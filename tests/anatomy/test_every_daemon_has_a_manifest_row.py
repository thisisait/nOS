"""Anatomy CI gate — every host daemon is bound to exactly one manifest row.

MEASURED 2026-10-05 (naming study): 11 of 19 `daemon:` nodes had no manifest
row, the openclaw row named a label no role renders (`eu.thisisait.nos.openclaw`;
the role starts `ai.openclaw.gateway`), wing and alloy rows had no
`launchd_label`, and `daemon:eu.thisisait.nos.ears` was the ears .app BUNDLE id,
harvested because its value merely looked like a label. Two representations of
one fact, no join between them. The join is `launchd_label` (+ `launchd_helpers`
for a row's second job); a daemon no service owns says why in
`daemons_without_row`; a host-native row with no launchd job says what it is in
`host_process`. Reads the graph and the manifest; never the live host.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _graph() -> dict:
    return json.loads((REPO / "state/anatomy-graph.json").read_text(encoding="utf-8"))["nodes"]


def _manifest() -> dict:
    return yaml.safe_load((REPO / "state/manifest.yml").read_text(encoding="utf-8"))


def _daemons() -> set[str]:
    return {k.split(":", 1)[1] for k, v in _graph().items() if v.get("kind") == "daemon"}


def _owners() -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for row in _manifest()["services"]:
        for label in [row.get("launchd_label"), *(row.get("launchd_helpers") or [])]:
            if label:
                owners.setdefault(label, []).append(row["id"])
    return owners


def test_every_daemon_has_one_row_or_a_reason():
    owners, reasons = _owners(), _manifest().get("daemons_without_row") or {}
    bad = []
    for label in sorted(_daemons()):
        rows = owners.get(label, [])
        if len(rows) > 1:
            bad.append(f"{label}: owned by {rows} — one daemon, one row")
        elif rows and label in reasons:
            bad.append(f"{label}: row {rows[0]} AND a daemons_without_row reason — pick one")
        elif not rows and not str(reasons.get(label) or "").strip():
            bad.append(f"{label}: no manifest row and no daemons_without_row reason")
    assert not bad, "\n".join(bad)


def test_every_declared_label_is_a_daemon_node():
    daemons = _daemons()
    stale = [f"manifest row {rows} names {label}" for label, rows in _owners().items()
             if label not in daemons]
    stale += [f"daemons_without_row names {label}"
              for label in (_manifest().get("daemons_without_row") or {}) if label not in daemons]
    assert not stale, "no role renders these labels:\n" + "\n".join(stale)


def test_a_host_native_row_names_its_daemon_or_what_it_is():
    bad = [row["id"] for row in _manifest()["services"]
           if row.get("stack") is None
           and not row.get("launchd_label") and not str(row.get("host_process") or "").strip()]
    assert not bad, f"stack: null rows with neither launchd_label nor host_process: {bad}"


def test_only_a_launchd_label_var_declares_a_daemon():
    """The ears bundle id became a daemon because its VALUE carried the
    eu.thisisait.nos. prefix. The declaration is the var name, not the shape."""
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni  # noqa: E402

    text = "\n".join([*(p.read_text(encoding="utf-8") for p in REPO.glob("roles/*/defaults/main.yml")),
                      ni.default_config_text()])  # every default layer, not one file
    declared = set(re.findall(r'^\w+_launchd_label:\s*"([\w.\-]+)"', text, re.M))
    declared |= {p.name.removesuffix(".plist.j2") for p in REPO.glob("templates/eu.thisisait.nos.*.plist.j2")}
    stray = sorted(_daemons() - declared)
    assert not stray, f"daemon nodes not declared by a *_launchd_label var: {stray}"


def test_a_host_native_service_is_not_described_as_docker():
    bad = [nid for nid, n in _graph().items()
           if n.get("kind") == "service" and n.get("stack") is None
           and "Docker" in n.get("description", "")]
    assert not bad, f"host-native rows described as Docker services: {bad}"
