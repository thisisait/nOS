"""`tools/undeclared-status.py`: what runs on the host that nOS never declared.

Workload allow-list, step 4 (roadmap `undeclared-status`). The converge knew
what it put on the host; nothing asked what ELSE was there — a LaunchAgent no
role wrote, a container published by hand, a crontab line. Pinned here against
fixtures, never the live host: the declared sets are DERIVED (graph roster,
repo plist templates, resolved manifest port_vars, rendered compose ports),
an unreadable axis is UNKNOWN, red-status carries the finding as one line, and
the reader has no mutating launchctl/crontab verb.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "undeclared-status.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_declared_labels_come_from_the_graph_and_the_templates(tmp_path, monkeypatch):
    mod = _load(TOOL, "_undecl_a")
    graph = tmp_path / "g.json"
    graph.write_text(json.dumps({"nodes": {
        "daemon:eu.thisisait.nos.bone": {"kind": "daemon"},
        "service:grafana": {"kind": "service"}}}))
    monkeypatch.setattr(mod, "GRAPH", graph)
    labels = mod.declared_labels()
    assert "eu.thisisait.nos.bone" in labels and "grafana" not in labels
    assert "com.ollama.agent" in labels, "pazny.openclaw writes it from a literal-Label template"


def test_an_undeclared_plist_and_a_stray_nos_label_are_named():
    mod = _load(TOOL, "_undecl_b")
    loaded = {"eu.thisisait.nos.bone": 10, "eu.thisisait.nos.legacy-x": 11,
              "com.vendor.agent": 12, "com.apple.Finder": 13}
    plists = {"eu.thisisait.nos.bone": {"path": "/u/L/bone.plist", "program": "/b"},
              "com.vendor.agent": {"path": "/u/L/v.plist", "program": "/v"},
              "com.root.daemon": {"path": "/Library/LaunchDaemons/r.plist", "program": "/r"}}
    rows = {r["label"]: r for r in mod.judge_launchd(loaded, plists, {"eu.thisisait.nos.bone"})}
    assert set(rows) == {"eu.thisisait.nos.legacy-x", "com.vendor.agent", "com.root.daemon"}
    assert rows["com.vendor.agent"]["loaded"] is True
    assert rows["com.root.daemon"]["loaded"] is None, "system domain is not asked, not 'not loaded'"


NETSTAT = """\
tcp4  0 0  127.0.0.1.3000  *.*  LISTEN  0 0 131072 131072 com.docker.backe:50  00100 00000006 0 0 00000800 1 0 000000
tcp4  0 0  127.0.0.1.4444  *.*  LISTEN  0 0 131072 131072 com.docker.backe:50  00100 00000006 0 0 00000800 1 0 000000
tcp46 0 0  *.18080         *.*  LISTEN  0 0 131072 131072             node:60  00100 00000106 0 0 00000800 1 0 000000
tcp4  0 0  127.0.0.1.5173  *.*  LISTEN  0 0 131072 131072             node:61  00100 00000106 0 0 00000800 1 0 000000
tcp4  0 0  *.9000          *.*  LISTEN  0 0 131072 131072       frankenphp:70  00100 00000106 0 0 00000800 1 0 000000
tcp4  0 0  *.5000          *.*  LISTEN  0 0 131072 131072     ControlCente:80  00100 00000106 0 0 00000800 1 0 000000
"""
PS = """\
50 1 /Applications/Docker.app/Contents/MacOS/com.docker.backend
60 1 node
61 1 node
70 1 /opt/homebrew/bin/frankenphp
80 1 /System/Library/CoreServices/ControlCenter.app/Contents/MacOS/ControlCenter
"""


def test_listeners_are_judged_against_declared_ports_and_daemon_pids(monkeypatch):
    mod = _load(TOOL, "_undecl_c")
    monkeypatch.setattr(mod, "_run", lambda *a, **k: NETSTAT if a[0] == "netstat" else PS)
    rows = mod.listeners()
    assert {r["port"] for r in rows} >= {18080}, "tcp46 (dual-stack) lines must parse"
    found = mod.judge_ports(rows, declared={3000}, daemon_pids={70})
    # 3000 declared, 5173 loopback user process, 9000 a declared daemon's pid,
    # 5000 the sealed system volume. A hand-published container and an exposed node stay.
    assert [(f["port"], pathlib.Path(f["exe"]).name) for f in found] == [
        (4444, "com.docker.backend"), (18080, "node")]


def test_declared_ports_read_the_rendered_compose_files(tmp_path, monkeypatch):
    mod = _load(TOOL, "_undecl_d")
    (tmp_path / "infra" / "overrides").mkdir(parents=True)
    (tmp_path / "infra" / "overrides" / "x.yml").write_text(
        "services:\n  x:\n    ports: ['127.0.0.1:7001:80', '7002:7002/udp', '7010-7011:7010-7011',"
        " '9999', {published: 7003, target: 1}]\n")
    monkeypatch.setattr(mod, "STACKS_DIR", tmp_path)
    ports = mod.declared_ports()
    assert {7001, 7002, 7003, 7010, 7011} <= ports and 9999 not in ports
    assert 5432 in ports, "postgresql_port resolved through the config layers"


def test_unreadable_axes_are_unknown_and_red_status_says_so(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise OSError("no such tool")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path / "absent"))
    red = _load(REPO / "tools" / "red-status.py", "_red_undecl")
    und = red.undeclared()
    assert und["items"] == [] and len(und["missing"]) == 3, und
    assert sum("UNKNOWN" in line for line in red.reds({"sources_missing": und["missing"]})) == 3


def test_red_status_carries_the_finding_as_one_line():
    red = _load(REPO / "tools" / "red-status.py", "_red_undecl2")
    lines = red.reds({"undeclared": ["port *:18080 (node)", "launchd com.vendor.agent (loaded)"]})
    hits = [line for line in lines if "declared nowhere" in line]
    assert len(hits) == 1 and "*:18080" in hits[0] and "com.vendor.agent" in hits[0]


MUTATING = {"load", "unload", "bootstrap", "bootout", "kickstart", "kill", "enable",
            "disable", "remove", "submit", "start", "stop", "-r", "-e", "-"}


def test_the_reader_has_no_mutating_verb():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if args and args[0] in ("launchctl", "crontab"):
                assert not MUTATING & set(args[1:]), args
        if isinstance(node, ast.Tuple):
            vals = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            if vals and vals[0] in ("launchctl", "crontab"):
                assert not MUTATING & set(vals[1:]), vals
