"""Anatomy CI gate — a committed table's anchor is not a known-broken node.

Two committed keap-tables once anchored [[nos.agents]], which existed nowhere,
and the KEAP lint reported it nightly for as long as they were there — the
detection existed, the commit gate did not (review agent, 2026-09-02).

The lint is the authority on what resolves (it runs inside KEAP against the
live taxonomy); this reads its broken-anchor findings back and refuses a
COMMITTED anchor that appears among them. Live-conditional: KEAP unreachable
is UNKNOWN — skip, never green. The reverse case (a LIVE table row drifted
from its committed anchor, e.g. face-controls still carrying nos.face) is the
planner's/judge-lint-queue's, not this gate's.
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
KEAP = "http://127.0.0.1:8091"


def _committed_anchors() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in sorted((REPO / "state" / "keap-tables").glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for a in doc.get("anchors") or []:
            out.setdefault(str(a), []).append(f.name)
    return out


def _broken_live() -> set[str]:
    try:
        store = yaml.safe_load((pathlib.Path.home() / ".nos" / "secrets.yml")
                               .read_text()) or {}
        tok = str(store.get("keap_agent_token_ro") or "")
    except OSError:
        tok = ""
    if not tok:
        pytest.skip("no keap_agent_token_ro — the lint is UNKNOWN here")
    req = urllib.request.Request(f"{KEAP}/agent/v1/lint",
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"KEAP is not answering: {exc}")
    return {str((f.get("data") or {}).get("anchor", ""))
            for f in (data.get("data") or {}).get("findings", [])
            if f.get("checkId") == "broken-anchor"}


def test_no_committed_anchor_is_a_known_broken_node():
    anchors = _committed_anchors()
    assert anchors, "no anchors found in state/keap-tables — the glob moved"
    broken = _broken_live()
    dangling = {a: files for a, files in anchors.items() if a in broken}
    assert not dangling, (
        f"committed anchor(s) the KEAP lint reports as broken: {dangling}. "
        "A table anchored to a node that does not exist is invisible in "
        "explore for as long as it is committed — [[nos.agents]] did this "
        "for weeks. Fix the anchor or create the node first")
