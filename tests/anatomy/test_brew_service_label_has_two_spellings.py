"""A Homebrew service label is one service under either spelling.

`brew services` named its launchd plists `homebrew.mxcl.<formula>` until
Homebrew 7, `sh.brew.<formula>` since. The manifest declares one spelling, the
host runs whichever its brew writes: on the first clean-machine deploy
(2026-10-09) tools/undeclared-status.py reported nOS's own dnsmasq row
(declared `homebrew.mxcl.dnsmasq`, running `sh.brew.dnsmasq`) as undeclared.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _reader():
    spec = importlib.util.spec_from_file_location("undeclared_status", REPO / "tools/undeclared-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plist(label):
    return {label: {"path": f"/Library/LaunchDaemons/{label}.plist", "program": "/opt/homebrew/sbin/x"}}


def test_either_brew_spelling_of_a_declared_label_is_declared(tmp_path):
    mod = _reader()
    graph = tmp_path / "anatomy-graph.json"
    graph.write_text(json.dumps({"nodes": {
        "service:dnsmasq": {"kind": "service", "launchd_labels": ["homebrew.mxcl.dnsmasq"]},
        "service:alloy": {"kind": "service", "launchd_labels": ["sh.brew.grafana-alloy"]},
    }}))
    mod.GRAPH = graph
    declared = mod.declared_labels()
    for running in ("sh.brew.dnsmasq", "homebrew.mxcl.grafana-alloy"):
        assert mod.judge_launchd({}, _plist(running), declared) == [], \
            f"{running} is a declared brew service under its other spelling"


def test_an_undeclared_brew_service_is_still_reported(tmp_path):
    mod = _reader()
    graph = tmp_path / "anatomy-graph.json"
    graph.write_text(json.dumps({"nodes": {}}))
    mod.GRAPH = graph
    out = mod.judge_launchd({}, _plist("sh.brew.postgresql@16"), mod.declared_labels())
    assert [d["label"] for d in out] == ["sh.brew.postgresql@16"]
