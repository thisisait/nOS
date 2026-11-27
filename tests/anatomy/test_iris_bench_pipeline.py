"""iris-bench judges the cortex plan path on the pipeline the thalamus recorded, never on its text.

Offline: a fake thalamus that answers the bench hello and plan_evidence (contract v20, row
cortex-plan-evidence-without-ledger, operator ruling 2026-11-11 (b)), and a fake /agent/v1/validate on
loopback answering canned reports. The bench opens no ledger file: the thalamus is asked, never the file.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import pathlib
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


def _accepted(case):
    """expect_pipeline is one plan or the list of plans any of which passes."""
    want = case.get("expect_pipeline") or []
    return [want] if isinstance(want, str) else want


def test_the_plan_cases_carry_an_expected_pipeline_and_the_rest_do_not():
    by = {c["id"]: c for c in CASES}
    assert [i for i in PLANNED if not by[i].get("expect_pipeline")] == []
    assert [i for i in FALLBACK if "expect_pipeline" in by[i]] == []


@pytest.mark.skipif(not (CORTEX / "node_modules/.bin/tsx").exists(),
                    reason="cortex node_modules absent — run `npm ci` in files/anatomy/cortex")
def test_every_expected_pipeline_is_valid_cortex_lang():
    """The vendored parser, not a regex: an expectation the validator refuses could never be met."""
    srcs = [s for c in CASES if "expect_pipeline" in c for s in _accepted(c)]
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


# ── a fake thalamus that answers the bench hello and plan_evidence, as serve.rs does ──

def _sid(n):
    return f"0b6f1d2e-3c4a-4b5d-8e9f-a0b1c2d3e4f{n}"


ASKED = {"engine": "llamacpp-gbnf", "constrained": True, "primer_sha256": "p" * 64, "grammar_sha256": "g" * 64,
         "catalogue": "lean", "catalogue_digest": "0123456789abcdef"}


def _ok(src):
    return {"valid": True, "registry_hash": HASH, "pipeline": src, "asked": ASKED}


class PlanFake(OFF.Fake):
    """OFF.Fake plus v20: the hello is answerless and accepted only first; plan_evidence answers the
    session this connection opened, from `evidence` ({} = it never planned), or is refused without a hello."""

    def __init__(self, script, evidence):
        self.evidence, self.kinds = evidence, []
        super().__init__(script)

    def conn(self, c):
        f = c.makefile("rw", encoding="utf-8")
        mine, session = [], None
        self.kinds.append(mine)
        for line in f:
            m = json.loads(line)
            self.seen.append(m)
            mine.append(m["t"])
            if m["t"] == "hello":
                continue
            if m["t"] == "turn":
                lines = self.script[m["text"]]
                session = lines[0]["session"]
            elif m["t"] == "plan_evidence" and mine[0] == "hello":
                lines = [{"t": "plan_evidence", "session": session, **self.evidence.get(session, {})}]
            else:
                lines = [{"t": "refused", "reason": "no bench hello on this connection"}]
            for x in lines:
                f.write(json.dumps(x) + "\n")
            f.flush()
        c.close()


CASE_FILE = [
    {"id": "same-plan", "prompt": "p1", "expect_pipeline": EXPECT, "checks": {"not_blank": True}},
    {"id": "wrong-plan", "prompt": "p2", "expect_pipeline": EXPECT, "checks": {"not_blank": True}},
    {"id": "broken-plan", "prompt": "p3", "expect_pipeline": EXPECT, "checks": {"not_blank": True}},
    {"id": "fallback-ok", "prompt": "p4", "checks": {"not_blank": True}},
    {"id": "planned-anyway", "prompt": "p5", "checks": {"not_blank": True}},
]
# BROKEN never validated, so its source never crosses: the thalamus sends only the fallback kind.
EVIDENCE = {_sid(1): _ok(SAID), _sid(2): _ok(WRONG), _sid(3): {"valid": False, "fallback": "model", "asked": ASKED},
            _sid(5): _ok(WRONG)}


def _script():
    return {f"p{n}": [{"t": "session", "session": _sid(n), "model_uri": "local-llamacpp-qwen"},
                      {"t": "text", "session": _sid(n), "text": "Done."},
                      {"t": "activity", "session": _sid(n), "phase": "idle"}] for n in range(1, 6)}


def _run(tmp_path, *extra, evidence=None):
    cases = tmp_path / "cases.yml"
    cases.write_text(yaml.safe_dump(CASE_FILE), encoding="utf-8")
    fake = PlanFake(_script(), EVIDENCE if evidence is None else evidence)
    out = tmp_path / "run.json"
    try:
        rc = OFF._bench().main(["--sock", fake.path, "--offline", "--out", str(out), "--timeout", "10",
                                "--cases", str(cases), *extra])
    finally:
        fake.close()
    return rc, json.loads(out.read_text()), fake


def test_a_cortex_run_is_judged_on_the_pipeline_the_thalamus_reports(tmp_path, validator):
    rc, run, fake = _run(tmp_path, "--plan", "cortex", "--validate-url", validator)
    res = {r["id"]: r for r in run["cases"]}
    assert res["same-plan"]["pass"], res["same-plan"]["failed"]
    assert res["wrong-plan"]["failed"] == ["pipeline_equals_expected"]
    assert set(res["broken-plan"]["failed"]) == {"pipeline_valid", "pipeline_equals_expected", "pipeline_fell_back"}
    assert res["fallback-ok"]["pass"], res["fallback-ok"]["failed"]          # no plan: fell back
    assert res["planned-anyway"]["failed"] == ["pipeline_fell_back"]        # absent expect = fallback is correct
    assert res["same-plan"]["pipeline"]["source"] == SAID and res["broken-plan"]["pipeline"]["fell_back"]
    # nos-assay import-iris-bench turns these into per-check rewards
    assert res["same-plan"]["plan_checks"] == ["pipeline_equals_expected", "pipeline_fell_back", "pipeline_valid"]
    assert res["fallback-ok"]["plan_checks"] == ["pipeline_fell_back"]
    assert rc == 1
    assert run["plan_path"] == "cortex" and run["provenance"]["plan"] == "cortex"
    assert run["engine"] == "llamacpp-gbnf" and run["registry_hash"] == HASH
    assert run["grammar_sha256"] == "g" * 64 and run["primer_sha256"] == "p" * 64
    # every judgement went through /validate with the RO bearer, the expectation too
    assert {p for p, _, _ in Validator.seen} == {"/agent/v1/validate"}
    assert {a for _, a, _ in Validator.seen} == {"Bearer ro-test-token"}
    assert EXPECT in {s for _, _, s in Validator.seen}
    # each case: the bench hello first, the evidence ask last, on the one connection
    assert fake.kinds and all(k[0] == "hello" and k[-1] == "plan_evidence" for k in fake.kinds), fake.kinds


def test_the_tools_path_judges_no_pipeline_and_asks_for_none(tmp_path, validator):
    rc, run, fake = _run(tmp_path, "--plan", "tools", "--validate-url", validator)
    assert rc == 0 and all(r["pass"] for r in run["cases"])
    assert all(r["plan_checks"] == [] for r in run["cases"])
    assert run["plan_path"] == "tools" and run["provenance"]["plan"] == "tools"
    assert Validator.seen == []
    assert all(k == ["turn"] for k in fake.kinds), fake.kinds


def test_an_unreachable_validator_is_named_not_scored_as_a_wrong_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_TOKEN_RO", "ro-test-token")
    rc, run, _ = _run(tmp_path, "--plan", "cortex", "--validate-url", "http://127.0.0.1:9")
    failed = {r["id"]: r["failed"] for r in run["cases"]}["same-plan"]
    assert failed and all("validator unreachable" in f for f in failed), failed


def test_cortex_plan_refuses_without_a_token(tmp_path, monkeypatch):
    fake = PlanFake(_script(), EVIDENCE)
    try:
        monkeypatch.delenv("CORTEX_TOKEN_RO", raising=False)
        assert OFF._bench().main(["--sock", fake.path, "--offline", "--out", str(tmp_path / "o.json"),
                                  "--plan", "cortex"]) == 2
    finally:
        fake.close()
    assert fake.connections == 0 and not (tmp_path / "o.json").exists()


def test_the_bench_opens_no_ledger_file():
    """The row's gate: the bench works with --ledger removed and imports no sqlite (parsed, not grepped)."""
    import ast
    tree = ast.parse((REPO / "tools/iris-bench.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    b = OFF._bench()
    assert "sqlite3" not in mods and not hasattr(b, "read_plan") and not hasattr(b, "read_route")


def test_a_refused_evidence_ask_is_named_never_a_verdict():
    """A thalamus that refuses plan_evidence (the session was not a bench session): the case says so."""
    b = OFF._bench()
    plan = b.plan_of({"t": "refused", "reason": "not a bench session"})
    assert "error" in plan and b.route_of(plan) is None


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


# Every case v3 can write carries its plan; only these fall back (or, multi-turn, go unjudged).
UNPLANNED = {
    "time-now": "a clock, not a table", "red-status": "a reader, not a db: stage",
    "unread-mail": "no mail table: honesty", "unread-mail-cs": "no mail table: honesty",
    "long-context-cs": "recall from the prompt", "long-context-en": "recall from the prompt",
    "table-create": "a schema card: no v3 verb", "column-add": "a schema card: no v3 verb",
    "choice-chart": "choice options are outside v3", "no-memory-hit": "search_memory, not a db: table",
    "memory-found": "search_memory, not a db: table", "services-known": "estate_services reader",
    "approvals-tier": "approvals reader", "dashboard-offer": "offer_dashboard is outside v3",
    "form-offer": "offer_dashboard is outside v3", "lines-dashboard": "offer_dashboard is outside v3",
    "guide-enable-n8n": "nos_guide steps", "guide-enable-n8n-cs": "nos_guide steps",
    "guide-update-cs": "nos_guide steps", "chain-cs": "its last turn is red_status",
}


def test_every_case_v3_expresses_carries_its_pipeline():
    assert set(UNPLANNED) <= {c["id"] for c in CASES}
    assert [c["id"] for c in CASES if (c["id"] in UNPLANNED) == bool(c.get("expect_pipeline"))] == []
    assert [c["id"] for c in CASES if not all(s.startswith(("get(db:", "insert(db:")) for s in _accepted(c))] == []


def test_a_multi_turn_case_without_a_plan_is_not_forced_to_fall_back():
    b = OFF._bench()  # the ledger is not sliced per turn: its last row may be an earlier turn's plan
    assert b.plan_checks({"id": "x", "turns": ["a", "b"]}, "cortex") == {}
    assert b.plan_checks({"id": "x", "prompt": "a"}, "cortex") == {"pipeline_fell_back": True}


def test_an_unjudged_plan_is_no_data_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_TOKEN_RO", "ro-test-token")
    rc, run, _ = _run(tmp_path, "--plan", "cortex", "--validate-url", "http://127.0.0.1:9")
    res = {r["id"]: r for r in run["cases"]}
    assert res["same-plan"]["no_data"] and not res["same-plan"]["pass"]
    assert not res["planned-anyway"]["no_data"]  # it planned when it should not: judged without the validator


def test_the_ro_token_goes_to_loopback_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_TOKEN_RO", "ro-test-token")
    (tmp_path / "c.yml").write_text(yaml.safe_dump(CASE_FILE[:1]), encoding="utf-8")
    b, sent = OFF._bench(), []
    monkeypatch.setattr(b, "validate_report", lambda url, *_: sent.append(url) or {"valid": False})
    fake = PlanFake(_script(), EVIDENCE)
    try:
        assert b.main(["--sock", fake.path, "--offline", "--out", str(tmp_path / "o.json"), "--plan", "cortex",
                       "--cases", str(tmp_path / "c.yml"), "--timeout", "10",
                       "--validate-url", "http://validator.example:8098"]) == 2
    finally:
        fake.close()
    assert sent == [] and fake.connections == 0 and not (tmp_path / "o.json").exists()


def test_an_expectation_may_list_the_plans_it_accepts():
    b = OFF._bench()
    got = {"plan": {"source": WRONG, "fell_back": False},
           "validate": lambda s: {"valid": s in REPORTS, "ast": REPORTS.get(s)}}
    assert b.check("pipeline_equals_expected", [EXPECT, WRONG], got, 0)
    assert not b.check("pipeline_equals_expected", [EXPECT], got, 0)
    with pytest.raises(ValueError):
        b.check("pipeline_equals_expected", [WRONG, BROKEN], got, 0)


# Ruling 2026-10-17: a count may stop at the rows or count them; "a chart" names no kind.
COUNTS = ("roadmap-count", "roadmap-count-cs", "where-not-q", "where-not-q-cs")


def test_a_count_accepts_the_rows_or_their_count_and_a_chart_any_kind():
    by = {c["id"]: c for c in CASES}
    for i in COUNTS:
        base = by[i]["expect_pipeline"][0]
        assert by[i]["expect_pipeline"] == [base, f"{base} | aggregate(op=count)"], i
    charts = by["next-by-track"]["expect_pipeline"]
    assert [p.split("chart=")[1].split(",")[0] for p in charts] == ["bar", "pie", "line"]


def test_an_estate_failure_is_no_data_not_a_plan_verdict():
    """serve.rs refused(): the organ down, the model unreachable or the catalogue unreadable is an infra
    fallback. Judging it would be a verdict on the model for the estate's failure: it is no data."""
    b = OFF._bench()
    plan = b.plan_of({"t": "plan_evidence", "session": _sid(1), "valid": False, "fallback": "infra"})
    assert plan is not None and plan["fallback_kind"] == "infra", plan
    for name, arg in (("pipeline_fell_back", True), ("pipeline_valid", True)):
        with pytest.raises(b.Unjudged):
            b.check(name, arg, {"plan": plan, "validate": lambda s: {"valid": True}}, 0.0)


def test_a_plan_is_equal_to_its_expectation_up_to_how_it_names_the_table_and_the_mappers_defaults():
    """The primer tells the model the operand is db:<table id> and the catalogue lists KEAP's ids (uuids),
    while every expect_pipeline names db:iris-bench-2 - so a compliant plan never compared equal. The
    plan row says which table the mapper resolved (said, id, title); either name is the same plan. And a
    param the mapper fills when absent (rank dir=desc, a chart's x = the aggregate's by) is the same plan."""
    b = OFF._bench()
    uid = "4f1c2a9e-0d3b-4e5f-9a8b-7c6d5e4f3a2b"
    said = _ast("s", ("get", [("db", uid)], {}), ("aggregate", [], {"op": "count", "by": "track"}),
                ("show", [], {"kind": "chart", "chart": "bar"}))
    want = _ast("w", ("get", T, {}), ("aggregate", [], {"op": "count", "by": "track"}),
                ("show", [], {"kind": "chart", "chart": "bar", "x": "track"}))
    table = {"said": uid, "id": uid, "title": "iris-bench-2"}
    assert b.same_pipeline(want, said, table)
    assert not b.same_pipeline(want, said, None), "without the mapper's resolution a uuid is another table"
    assert not b.same_pipeline(_ast("x", ("get", [("db", "iris-bench-3")], {})), _ast("y", ("get", [("db", uid)], {})), table)
    ranked = _ast("r", ("get", T, {}), ("rank", [], {"by": "points"}))
    assert b.same_pipeline(_ast("r2", ("get", T, {}), ("rank", [], {"by": "points", "dir": "desc"})), ranked, table)
    assert not b.same_pipeline(_ast("r3", ("get", T, {}), ("rank", [], {"by": "points", "dir": "asc"})), ranked, table)
