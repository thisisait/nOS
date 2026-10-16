"""tools/oneshot-poc.py: a question battery compiles a thalamus tool plan, validated dry, traced in full.

Offline only: the scripted fake models of state/fixtures/oneshot/fake-answers.yml. The pinned tool
list there is serve::tools() (thalamus/tests/tool_schemas.rs); the names are also checked here.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "oneshot-poc.py"
SCRIPTS = yaml.safe_load((REPO / "state/fixtures/oneshot/fake-answers.yml").read_text(encoding="utf-8"))


def _poc():
    spec = importlib.util.spec_from_file_location("oneshot_poc", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path, monkeypatch, *args):
    poc = _poc()
    monkeypatch.delenv("NOS_LIVE", raising=False)
    monkeypatch.setattr(poc, "_ollama", lambda *a: pytest.fail("offline run reached Ollama"))
    rc = poc.main(["--trace", str(tmp_path / "t.jsonl"), "--out", str(tmp_path / "r.json"), *args])
    trace = [json.loads(x) for x in (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()]
    return rc, json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["cases"], trace


def test_the_fake_run_compiles_the_expected_plans(tmp_path, monkeypatch):
    rc, cases, _ = _run(tmp_path, monkeypatch)
    by = {c["id"]: c for c in cases}
    assert rc == 0 and set(by) == {"top3-next", "where-not-q", "bar-sum-points", "edit-card"}, cases
    assert all(c["ok"] and not c["failed"] for c in cases), cases
    assert by["top3-next"]["plan"] == [{"tool": "query_rows", "args": {
        "table": "iris-bench-2", "limit": 3, "order_by": {"column": "points", "dir": "desc"},
        "where": [{"column": "status", "op": "eq", "value": "next"}]}}]
    assert by["bar-sum-points"]["plan"][0]["args"]["source"] == {
        "query": {"table": "iris-bench-2", "where": [{"column": "status", "op": "eq", "value": "next"}]},
        "op": "sum", "x": "track", "y": "points"}
    assert [s["tool"] for s in by["edit-card"]["plan"]] == ["query_rows", "propose_row_edit"]
    assert by["edit-card"]["plan"][1]["args"] == {"table": "iris-bench-2", "row_id": "$step1.rows[0].__id",
                                                  "values": {"status": "shipped"}}


def test_every_tool_question_offers_the_full_tool_list(tmp_path, monkeypatch):
    serve = (REPO / "files/anatomy/thalamus/thalamus/src/serve.rs").read_text(encoding="utf-8")
    body = serve[serve.index("pub fn tools()"):]
    body = body[:body.index("\n}\n")]
    names = re.findall(r'"name": "(\w+)", "description"', body) + ["propose_table_create", "propose_column_add"]
    poc = _poc()
    assert sorted(poc.SCHEMAS) == sorted(names), "the pinned tool list drifted from serve.rs"
    _, _, trace = _run(tmp_path, monkeypatch)
    asked = [r for r in trace if r["id"].endswith(".tool")]
    assert len(asked) == 5  # 3 one-call cases ask one step; edit-card 2 (its "no more" is s3.more)
    assert all(r["options"] == list(poc.SCHEMAS) + ["done"] for r in asked), asked


def test_the_compiler_refuses_a_schema_invalid_call():
    poc = _poc()
    good = dict(SCRIPTS["where-not-q"]["answers"], **{f"sys.{s}": s == "keap_table" for s in poc.CATALOGUE["systems"]},
                multi_step=False)
    assert poc.compile_answers("r", good)["plan"][0]["tool"] == "query_rows"
    # every answer within its question's constraint, the call outside its schema (question minLength 1)
    bad = {**{k: v for k, v in good.items() if not k.startswith("s1.")}, "s1.tool": "nos_guide", "s1.question": "",
           "s2.tool": "done"}
    with pytest.raises(poc.Refused, match="nos_guide"):
        poc.compile_answers("r", bad)
    with pytest.raises(poc.Refused, match="limit"):
        poc.compile_answers("r", dict(good, **{"s1.limit": 99}))  # past the question's max, never clamped
    with pytest.raises(poc.Refused, match="earlier query_rows"):
        poc.validate([{"tool": "propose_row_delete", "args": {"table": "t", "row_id": "$step1.rows[0].__id"}}])
    with pytest.raises(poc.Refused, match="maximum"):
        poc.validate([{"tool": "query_rows", "args": {"table": "t", "limit": 99}}])


def test_the_trace_records_every_question(tmp_path, monkeypatch):
    _, cases, trace = _run(tmp_path, monkeypatch)
    for c in cases:
        rows = [r for r in trace if r["case"] == c["id"] and r["id"] != "normalised"]
        assert len(rows) == c["questions"] > 0, c["id"]
        assert all({"text", "kind", "answer", "ms"} <= set(r) for r in rows)
    # a question the fake cannot answer is traced before the case fails
    fake = tmp_path / "fake.yml"
    fake.write_text(yaml.safe_dump({"top3-next": SCRIPTS["top3-next"] | {
        "answers": {k: v for k, v in SCRIPTS["top3-next"]["answers"].items() if k != "s1.limit"}}}), encoding="utf-8")
    rc, cases, trace = _run(tmp_path, monkeypatch, "--fake", str(fake))
    assert rc == 1 and "unscripted question s1.limit" in cases[0]["error"]
    assert trace[-1]["id"] == "s1.limit" and "refused" in trace[-1]
    assert len([r for r in trace if r["id"] != "normalised"]) == cases[0]["questions"]


def test_the_embed_scorer_hands_back_under_the_margin():
    poc = _poc()
    assert poc.pick_by_margin([1, 0], [[1, 0], [0, 1]], 0.05)[0] == 0
    pick, lead = poc.pick_by_margin([1, 1], [[1, 0.9], [0.9, 1]], 0.05)
    assert pick is None and lead < 0.05
