"""iris-bench judges the cortex plan path on the pipeline the thalamus recorded, never on its text.

Offline: a fake thalamus (test_iris_bench_offline.Fake), a fake /agent/v1/validate on loopback
answering canned reports, and a temp ledger.db this test writes. The real ~/.nos ledger is never
opened: --plan cortex refuses to run without an explicit --ledger.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import threading

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CORTEX = REPO / "files/anatomy/cortex"
CASES = yaml.safe_load((REPO / "state/fixtures/iris-bench.yml").read_text(encoding="utf-8"))
PLANNED = ("top3-next", "bar-sum-points", "line-due", "total-sum", "due-between", "kpi-total")
FALLBACK = ("choice-chart", "dashboard-offer")  # offer_dashboard and choice options are out of v3
HASH = "cx1:8250d05e5e32afb7"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OFF = _load("iris_bench_offline", pathlib.Path(__file__).with_name("test_iris_bench_offline.py"))


def test_the_plan_cases_carry_an_expected_pipeline_and_the_rest_do_not():
    by = {c["id"]: c for c in CASES}
    assert [i for i in PLANNED if not by[i].get("expect_pipeline")] == []
    assert [i for i in FALLBACK if "expect_pipeline" in by[i]] == []


@pytest.mark.skipif(not (CORTEX / "node_modules/.bin/tsx").exists(),
                    reason="cortex node_modules absent — run `npm ci` in files/anatomy/cortex")
def test_every_expected_pipeline_is_valid_cortex_lang():
    """The vendored parser, not a regex: an expectation the validator refuses could never be met."""
    srcs = [c["expect_pipeline"] for c in CASES if "expect_pipeline" in c]
    assert srcs
    js = ("import { analyzeCortex } from './server/cortex-lang';"
          "const s = JSON.parse(process.argv[1]);"
          "console.log(JSON.stringify(s.map((x: string) => analyzeCortex(x).errors.map(e => e.code))));")
    done = subprocess.run(["npx", "tsx", "-e", js, json.dumps(srcs)], capture_output=True, text=True, cwd=CORTEX, timeout=120)
    assert done.returncode == 0, done.stderr[-600:]
    bad = {s: e for s, e in zip(srcs, json.loads(done.stdout)) if e}
    assert bad == {}


# ── the fake validator: canned reports keyed by source ──

def _ast(source, *stages):
    """A /validate AST; spans hang off the source text so two spellings differ only there."""
    off = len(source)
    return {"astVersion": 1, "source": source, "deferred": [],
            "binding": {"opcodeRegistryHash": HASH},
            "pipeline": {"source": None, "stages": [
                {"index": i, "opcode": op, "mutating": False, "effective": {}, "span": [off + i, off + i + 1],
                 "operands": [{"ns": ns, "kind": "deferred", "binding": "exact", "scopeHint": None, "surface": s,
                               "id": None, "resolvedName": None, "span": [off, off + 1]} for ns, s in opnds],
                 "params": {k: {"value": v, "defaulted": False, "span": [off, off + 2]} for k, v in params.items()}}
                for i, (op, opnds, params) in enumerate(stages)]}}


T = [("db", "iris-bench-2")]
EXPECT = 'get(db:iris-bench-2) | aggregate(op=sum, y=points)'
SAID = 'get(db:iris-bench-2)|aggregate(y="points", op=sum)'   # the same plan, spelled differently
WRONG = 'get(db:iris-bench-2) | aggregate(op=count)'
BROKEN = 'get(db:iris-bench-2) | aggregate('
REPORTS = {
    EXPECT: _ast(EXPECT, ("get", T, {}), ("aggregate", [], {"op": "sum", "y": "points"})),
    SAID: _ast(SAID, ("get", T, {}), ("aggregate", [], {"y": "points", "op": "sum"})),
    WRONG: _ast(WRONG, ("get", T, {}), ("aggregate", [], {"op": "count"})),
}


class Validator(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Validator.seen.append((self.path, self.headers.get("authorization"), body["source"]))
        ast = REPORTS.get(body["source"])
        data = {"valid": ast is not None, "ast": ast,
                "errors": [] if ast else [{"code": "syntax_error", "message": "unexpected <eof>"}]}
        raw = json.dumps({"ok": True, "data": data}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.setenv("CORTEX_TOKEN_RO", "ro-test-token")
    Validator.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), Validator)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


# ── a temp ledger, shaped like thalamus/src/ledger.rs ──

def _sid(n):
    return f"0b6f1d2e-3c4a-4b5d-8e9f-a0b1c2d3e4f{n}"


def _ledger(path, plans):
    """plans: {session: (source, fallback-or-None)}; a session absent from it never planned."""
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE sessions (id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, agent_name TEXT);"
                     "CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, run_id TEXT, type TEXT, task TEXT,"
                     " result_json TEXT, source TEXT);")
    for sid, (src, fallback) in plans.items():
        db.execute("INSERT INTO sessions (uuid, agent_name) VALUES (?, 'iris')", (sid,))
        use = {"source": src, "engine": "llamacpp-gbnf", "constrained": True,
               "grammar_sha256": "g" * 64, "primer_sha256": "p" * 64}
        res = {"valid": fallback is None, "errors": [], "registry_hash": HASH}
        res |= {"fallback": fallback} if fallback else {"plan": [{"tool": "query_rows"}]}
        for kind, body in (("agent_tool_use", use), ("agent_tool_result", res)):
            db.execute("INSERT INTO events (ts, run_id, type, task, result_json, source) VALUES "
                       "('t', ?, ?, 'agent:iris/tool:cortex_plan', ?, 'thalamus')", (sid, kind, json.dumps(body)))
        db.execute("INSERT INTO events (ts, run_id, type, task, result_json) VALUES "
                   "('t', ?, 'agent_tool_use', 'agent:iris/tool:query_rows', '{}')", (sid,))
    db.commit()
    db.close()


CASE_FILE = [
    {"id": "same-plan", "prompt": "p1", "expect_pipeline": EXPECT, "checks": {"not_blank": True}},
    {"id": "wrong-plan", "prompt": "p2", "expect_pipeline": EXPECT, "checks": {"not_blank": True}},
    {"id": "broken-plan", "prompt": "p3", "expect_pipeline": EXPECT, "checks": {"not_blank": True}},
    {"id": "fallback-ok", "prompt": "p4", "checks": {"not_blank": True}},
    {"id": "planned-anyway", "prompt": "p5", "checks": {"not_blank": True}},
]


def _script():
    return {f"p{n}": [{"t": "session", "session": _sid(n), "model_uri": "local-llamacpp-qwen"},
                      {"t": "text", "session": _sid(n), "text": "Done."},
                      {"t": "activity", "session": _sid(n), "phase": "idle"}] for n in range(1, 6)}


def _run(tmp_path, *extra, plans=None):
    cases = tmp_path / "cases.yml"
    cases.write_text(yaml.safe_dump(CASE_FILE), encoding="utf-8")
    led = tmp_path / "ledger.db"
    _ledger(led, plans if plans is not None else {
        _sid(1): (SAID, None), _sid(2): (WRONG, None), _sid(3): (BROKEN, "invalid: syntax_error"),
        _sid(5): (WRONG, None)})
    before = led.read_bytes()
    fake = OFF.Fake(_script())
    out = tmp_path / "run.json"
    try:
        rc = OFF._bench().main(["--sock", fake.path, "--offline", "--out", str(out), "--timeout", "10",
                                "--cases", str(cases), "--ledger", str(led), *extra])
    finally:
        fake.close()
    assert led.read_bytes() == before, "the bench wrote to the ledger"
    assert not led.with_name("ledger.db-wal").exists()
    return rc, json.loads(out.read_text()), fake


def test_a_cortex_run_is_judged_on_the_pipeline_the_ledger_holds(tmp_path, validator):
    rc, run, _ = _run(tmp_path, "--plan", "cortex", "--validate-url", validator)
    res = {r["id"]: r for r in run["cases"]}
    assert res["same-plan"]["pass"], res["same-plan"]["failed"]
    assert res["wrong-plan"]["failed"] == ["pipeline_equals_expected"]
    assert set(res["broken-plan"]["failed"]) == {"pipeline_valid", "pipeline_equals_expected", "pipeline_fell_back"}
    assert res["fallback-ok"]["pass"], res["fallback-ok"]["failed"]          # no plan row: fell back
    assert res["planned-anyway"]["failed"] == ["pipeline_fell_back"]        # absent expect = fallback is correct
    assert res["same-plan"]["pipeline"]["source"] == SAID and res["broken-plan"]["pipeline"]["fell_back"]
    assert rc == 1
    assert run["plan_path"] == "cortex" and run["provenance"]["plan"] == "cortex"
    assert run["engine"] == "llamacpp-gbnf" and run["registry_hash"] == HASH
    assert run["grammar_sha256"] == "g" * 64 and run["primer_sha256"] == "p" * 64
    # every judgement went through /validate with the RO bearer, the expectation too
    assert {p for p, _, _ in Validator.seen} == {"/agent/v1/validate"}
    assert {a for _, a, _ in Validator.seen} == {"Bearer ro-test-token"}
    assert EXPECT in {s for _, _, s in Validator.seen}


def test_the_tools_path_judges_no_pipeline(tmp_path, validator):
    rc, run, _ = _run(tmp_path, "--plan", "tools", "--validate-url", validator)
    assert rc == 0 and all(r["pass"] for r in run["cases"])
    assert run["plan_path"] == "tools" and run["provenance"]["plan"] == "tools"
    assert Validator.seen == []


def test_an_unreachable_validator_is_named_not_scored_as_a_wrong_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_TOKEN_RO", "ro-test-token")
    rc, run, _ = _run(tmp_path, "--plan", "cortex", "--validate-url", "http://127.0.0.1:9")
    failed = {r["id"]: r["failed"] for r in run["cases"]}["same-plan"]
    assert failed and all("validator unreachable" in f for f in failed), failed


def test_cortex_plan_refuses_without_a_ledger_or_a_token(tmp_path, monkeypatch):
    fake = OFF.Fake(_script())
    try:
        monkeypatch.setenv("CORTEX_TOKEN_RO", "x")
        assert OFF._bench().main(["--sock", fake.path, "--offline", "--out", str(tmp_path / "o.json"),
                                  "--plan", "cortex"]) == 2
        monkeypatch.delenv("CORTEX_TOKEN_RO")
        (tmp_path / "l.db").write_bytes(b"")
        assert OFF._bench().main(["--sock", fake.path, "--offline", "--out", str(tmp_path / "o.json"),
                                  "--plan", "cortex", "--ledger", str(tmp_path / "l.db")]) == 2
    finally:
        fake.close()
    assert fake.connections == 0 and not (tmp_path / "o.json").exists()


def test_the_ast_comparison_is_op_by_op_not_text():
    b = OFF._bench()
    same = b.same_pipeline(REPORTS[EXPECT], REPORTS[SAID])
    assert same and not b.same_pipeline(REPORTS[EXPECT], REPORTS[WRONG])
    # a cosmetic show param is not the plan; a different operand is
    kpi = _ast("a", ("show", [], {"kind": "kpi"}))
    titled = _ast("b", ("show", [], {"kind": "kpi", "title": "Total"}))
    other = _ast("c", ("get", [("db", "iris-bench-3")], {}))
    assert b.same_pipeline(kpi, titled)
    assert not b.same_pipeline(_ast("d", ("get", T, {})), other)
