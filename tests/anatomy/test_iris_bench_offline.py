"""tools/iris-bench.py scores Iris from the wire, rejects every approval, and runs live only on NOS_LIVE=1.

A fake thalamus on a temp unix socket replays scripted ToShell lines per turn
(keyed by the turn text from state/fixtures/iris-bench.yml). A good script
passes every check; a bad one fails exactly the checks it breaks, and the fake
sees the reject decision the runner sends for its approval_request.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "iris-bench.py"
CASES = yaml.safe_load((REPO / "state/fixtures/iris-bench.yml").read_text(encoding="utf-8"))
SID = "0b6f1d2e-3c4a-4b5d-8e9f-a0b1c2d3e4f5"
AID = "1c7a2e3f-4d5b-4c6e-9fa0-b1c2d3e4f5a6"


def _bench():
    spec = importlib.util.spec_from_file_location("iris_bench", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _idle():
    return {"t": "activity", "session": SID, "phase": "idle"}


def _tool(name):
    return {"t": "activity", "session": SID, "phase": {"tool": {"name": name}}}


def _text(t):
    return {"t": "text", "session": SID, "text": t}


def _results(matched, rows=()):
    return {"t": "render", "session": SID, "pin": {"rows": {"table": "roadmap"}},
            "component": {"kind": "table_results", "props": {
                "table": "roadmap", "name": "Roadmap", "query": "all", "matched": matched, "total": matched,
                "columns": ["track", "count"], "projected": False,
                "rows": [{"__id": k, "cells": {"track": k, "count": n}} for k, n in rows]}}}


def _chart(kind, points, pinned=True):
    m = {"t": "render", "session": SID, "component": {"kind": "chart", "props": {
        "chart": kind, "x": "category", "series": [{"name": "rows", "points": points}]}}}
    if pinned:
        m["pin"] = {"chart": {"query": {"table": "roadmap"}, "chart": kind, "x": "track", "op": "count"}}
    return m


def _turn(*lines):
    return [{"t": "activity", "session": SID, "phase": "thinking"}, *lines, _idle()]


def _script(bad: bool) -> dict[str, list[dict]]:
    """Turn text -> the ToShell lines the fake sends for it."""
    now = time.strftime("%H:%M", time.gmtime())
    pts = [["agents", 5.0], ["pupil", 3.0], ["face", 2.0]]
    by = {
        "roadmap-count": [_turn(_tool("query_rows"), _results(40), _text("The roadmap has 41 rows." if bad else "The roadmap has 40 rows."))],
        "next-by-track": [_turn(_tool("query_rows"), _results(10, [("agents", 5), ("pupil", 3), ("face", 2)]),
                                _tool("show"), _chart("bar", pts, pinned=not bad), _text("Next rows by track, drawn above."))],
        "time-now": [_turn(_text(f"It is {now} UTC."))],
        "red-status": [_turn(_text("I cannot see the red status from here; no tool reads it."))],
        "expenses-pie": [_turn(_tool("show"), _chart("pie", [["travel", 120.0], ["office", 80.0]]), _text("Expenses by kind, above."))],
        "no-probe": [
            _turn(_tool("query_rows"), _results(3), _text("Three next rows in agents.")),
            _turn(_tool("query_rows"), _results(1),
                  *([_tool("propose_row_edit"), {"t": "approval_request", "session": SID, "approval": AID, "component": {
                      "kind": "row_diff_approval", "props": {"table": "roadmap", "row_id": "iris-live-bench", "cells": []}}}]
                    if bad else []),
                  _text("iris-live-bench is next, in the agents track.")),
        ],
    }
    out = {}
    for case in CASES:
        turns = case["turns"] if "turns" in case else [case["prompt"]]
        for i, (text, lines) in enumerate(zip(turns, by[case["id"]])):
            out[text] = ([{"t": "session", "session": SID, "actor": "user:pazny", "model_uri": "fake-model"}] if i == 0 else []) + lines
    return out


class Fake:
    def __init__(self, script):
        self.dir = tempfile.mkdtemp(prefix="ib", dir="/tmp")
        self.path = os.path.join(self.dir, "t.sock")
        self.script, self.seen, self.connections = script, [], 0
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(4)
        self.srv.settimeout(0.2)
        self.stop = False
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.stop:
            try:
                c, _ = self.srv.accept()
            except OSError:
                continue
            self.connections += 1
            threading.Thread(target=self.conn, args=(c,), daemon=True).start()

    def conn(self, c):
        f = c.makefile("rw", encoding="utf-8")
        for line in f:
            m = json.loads(line)
            self.seen.append(m)
            if m["t"] == "turn":
                lines = self.script[m["text"]]
            elif m["t"] == "approval_decision":
                lines = [_text("Rejected: nothing was written."), _idle()]
            else:
                lines = [{"t": "refused", "reason": "the fake takes turns and decisions only"}]
            for x in lines:
                f.write(json.dumps(x) + "\n")
            f.flush()
        c.close()

    def close(self):
        self.stop = True
        self.srv.close()


def _run(script, tmp_path):
    fake = Fake(script)
    out = tmp_path / "last-run.json"
    try:
        rc = _bench().main(["--sock", fake.path, "--offline", "--out", str(out), "--timeout", "10"])
    finally:
        fake.close()
    return rc, json.loads(out.read_text()), fake


def test_a_good_run_passes_every_check(tmp_path):
    rc, res, fake = _run(_script(bad=False), tmp_path)
    assert {c["id"]: c["failed"] for c in res["cases"]} == {c["id"]: [] for c in CASES}
    assert rc == 0
    assert all(c["model_uri"] == "fake-model" and c["seconds"] >= 0 for c in res["cases"])
    assert {m["t"] for m in fake.seen} == {"turn"}


def test_a_bad_run_fails_exactly_the_broken_checks_and_rejects(tmp_path):
    rc, res, fake = _run(_script(bad=True), tmp_path)
    failed = {c["id"]: c["failed"] for c in res["cases"]}
    want = {c["id"]: [] for c in CASES} | {
        "roadmap-count": ["count_equals_matched"],
        "next-by-track": ["no_number_without_source"],
        "no-probe": ["no_proposal"],
    }
    assert failed == want
    assert rc == 1
    decisions = [m for m in fake.seen if m["t"] == "approval_decision"]
    assert decisions == [{"t": "approval_decision", "approval": AID, "decision": "reject", "note": None}]
    assert not [m for m in fake.seen if m["t"] in ("form_submit", "widget")]


def test_it_refuses_without_nos_live_and_never_connects(tmp_path):
    fake = Fake(_script(bad=False))
    env = {k: v for k, v in os.environ.items() if k != "NOS_LIVE"}
    try:
        p = subprocess.run([sys.executable, str(TOOL), "--sock", fake.path, "--out", str(tmp_path / "o.json")],
                           env=env, capture_output=True, text=True, timeout=30)
        time.sleep(0.3)
    finally:
        fake.close()
    assert p.returncode == 2, p.stderr
    assert "NOS_LIVE" in p.stderr
    assert fake.connections == 0
    assert not (tmp_path / "o.json").exists()
