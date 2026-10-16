"""iris-bench per-turn scoring: dict turns {say, checks} judged on their own slice of the wire, gated.

Turn N is judged only while every earlier turn passed; after a failure the rest are not_reached.
A case's `kind` is copied to its result; --seed --domain creates the domain's tables from
$NOS_ASSAY_DIR/domains/<d>/tables/*.table.yml (a fake KEAP here, never the live one).
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OFF = _load("iris_bench_offline", "tests/anatomy/test_iris_bench_offline.py")
NEXT = [{"column": "status", "op": "eq", "value": "next"}]

CASE = {"id": "next-then-chart", "kind": "follow-up", "turns": [
    {"say": "How many rows are next?", "checks": {"query_uses": {"where": NEXT}, "count_equals_matched": True}},
    {"say": "Now chart them by track.", "checks": {"chart_source": "same as turn 0", "tools_not_called": ["query_rows"]}},
    {"say": "And the top three?", "checks": {"query_uses": {"where": "same as turn 0", "limit": 3}}},
]}


def _turns(chart_where=NEXT, first_text="8 rows are next."):
    """The fake's lines per say: turn 1 draws a pinned chart whose where is `chart_where`."""
    chart = OFF._pinned_chart("bar", "track", "count", where=chart_where)
    return {
        "How many rows are next?": [{"t": "session", "session": OFF.SID, "model_uri": "fake-model"},
                                    *OFF._turn(OFF._tool("query_rows"), OFF._read({"table": "t", "where": NEXT}, ["a"] * 8),
                                               OFF._text(first_text))],
        "Now chart them by track.": OFF._turn(OFF._tool("show"), chart, OFF._text("Drawn above.")),
        "And the top three?": OFF._turn(OFF._tool("query_rows"), OFF._read({"table": "t", "where": NEXT, "limit": 3}, ["a"] * 3),
                                        OFF._text("Above.")),
    }


def _run(tmp_path, script, cases):
    p = tmp_path / "cases.yml"
    p.write_text(yaml.safe_dump(cases), encoding="utf-8")
    fake, out = OFF.Fake(script), tmp_path / "run.json"
    try:
        rc = OFF._bench().main(["--sock", fake.path, "--offline", "--cases", str(p), "--out", str(out), "--timeout", "5"])
    finally:
        fake.close()
    return rc, json.loads(out.read_text())["cases"][0], fake


def test_every_turn_passes_on_its_own_slice(tmp_path, capsys):
    rc, r, fake = _run(tmp_path, _turns(), [CASE])
    assert [t["status"] for t in r["turns"]] == ["pass", "pass", "pass"], r
    assert r["turns"][0] == {"index": 0, "status": "pass", "failed": []}
    assert r["depth"] == 3 and r["pass"] and rc == 0
    assert r["kind"] == "follow-up"
    # Turn 1 is judged on its slice: the query_rows of turn 0 is not its own.
    assert [m["text"] for m in fake.seen if m["t"] == "turn"] == [t["say"] for t in CASE["turns"]]
    assert "mean depth 3.00" in capsys.readouterr().out


def test_a_failed_turn_gates_the_rest(tmp_path):
    rc, r, _ = _run(tmp_path, _turns(chart_where=[]), [CASE])
    assert [t["status"] for t in r["turns"]] == ["pass", "fail", "not_reached"], r
    assert r["turns"][1]["failed"] == ["chart_source"] and r["turns"][2]["failed"] == []
    assert r["depth"] == 1 and not r["pass"] and rc == 1
    assert r["failed"] == ["turn 1: chart_source"]


def test_the_first_turn_failing_is_depth_zero(tmp_path):
    _, r, _ = _run(tmp_path, _turns(first_text="Nine rows."), [CASE])
    assert [t["status"] for t in r["turns"]] == ["fail", "not_reached", "not_reached"]
    assert r["turns"][0]["failed"] == ["count_equals_matched"] and r["depth"] == 0


def test_plain_cases_score_as_before_and_carry_no_invented_kind(tmp_path):
    plain = {"id": "plain", "turns": ["How many rows are next?", "Now chart them by track."],
             "checks": {"tools_called": ["query_rows", "show"]}}
    rc, r, _ = _run(tmp_path, _turns(), [plain])
    assert r["pass"] and r["failed"] == [] and r["kind"] is None and rc == 0
    # Case-level checks see the whole wire, so they are judged with the last turn.
    assert [t["status"] for t in r["turns"]] == ["pass", "pass"] and r["depth"] == 2
    bad = dict(plain, checks={"tools_called": ["red_status"]})
    _, r, _ = _run(tmp_path, _turns(), [bad])
    assert r["failed"] == ["tools_called"] and [t["status"] for t in r["turns"]] == ["pass", "fail"] and r["depth"] == 1


def test_same_as_turn_n_is_the_where_of_that_turns_last_query():
    """`same as turn N`: the where list of turn N's LAST pinned query (a query_rows read, else a chart's or kpi's query)."""
    b = OFF._bench()
    t0 = OFF._got(renders=[OFF._read({"table": "t", "where": [{"column": "x", "op": "eq", "value": 1}]}),
                           OFF._read({"table": "t", "where": NEXT})])
    t1 = OFF._got(renders=[OFF._pinned_chart("bar", "track", "count", where=NEXT)])
    assert b.resolve_arg("same as turn 0", [t0]) == {"where": NEXT}
    assert b.resolve_arg({"where": "same as turn 1", "limit": 3}, [t0, t1]) == {"where": NEXT, "limit": 3}
    assert b.resolve_arg({"limit": 3}, [t0]) == {"limit": 3}
    for missing in ("same as turn 2", {"where": "same as turn 0"}):
        with pytest.raises(LookupError):
            b.resolve_arg(missing, [] if missing != "same as turn 2" else [t0, t1])
    with pytest.raises(LookupError):
        b.resolve_arg("same as turn 0", [OFF._got()])  # turn 0 queried nothing


def test_oneshot_reads_the_say_text_of_dict_turns(tmp_path):
    poc, seen = _load("oneshot_poc", "tools/oneshot-poc.py"), []

    def norm(turns):
        seen.append(turns)
        raise ValueError("stop here")
    res = poc.run(CASE, norm, None, io.StringIO())
    assert seen == [[t["say"] for t in CASE["turns"]]] and "stop here" in res["error"]


class FakeKeap:
    def __init__(self, have=()):
        self.posts, self.have = [], [{"id": f"t{i}", "title": t} for i, t in enumerate(have)]

    def tables(self):
        return self.have

    def req(self, method, path, body=None):
        self.posts.append((method, path, body))
        return 200, {"data": {"id": "new-" + str(len(self.posts))}}


def _domain(tmp_path):
    d = tmp_path / "domains/d1/tables"
    d.mkdir(parents=True)
    (d / "parts.table.yml").write_text(yaml.safe_dump({
        "title": "parts", "description": "synthetic", "driver": "libsql", "visibility": "shared", "anchors": [],
        "schema": {"columns": [{"key": "name", "label": "Name", "kind": "text", "role": "dimension"}]},
        "rows": [{"name": "bolt"}, {"name": "nut"}]}), encoding="utf-8")
    return tmp_path


def test_seed_domain_creates_its_tables_and_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_ASSAY_DIR", str(_domain(tmp_path)))
    monkeypatch.setenv("NOS_LIVE", "1")
    b, keap = OFF._bench(), FakeKeap()
    monkeypatch.setattr(b, "_dtt", lambda: keap)
    assert b.main(["--seed", "--domain", "d1"]) == 0
    create = keap.posts[0]
    assert create[:2] == ("POST", "/api/tables") and "rows" not in create[2] and create[2]["title"] == "parts"
    assert create[2]["schema"]["columns"][0]["key"] == "name"
    assert keap.posts[1:] == [("POST", "/api/tables/new-1/rows", {"values": {"name": "bolt"}}),
                              ("POST", "/api/tables/new-1/rows", {"values": {"name": "nut"}})]
    keap = FakeKeap(have=["parts"])
    monkeypatch.setattr(b, "_dtt", lambda: keap)
    assert b.main(["--seed", "--domain", "d1"]) == 0 and keap.posts == [], "an existing table is left alone"


def test_seed_domain_needs_nos_live(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_ASSAY_DIR", str(_domain(tmp_path)))
    monkeypatch.delenv("NOS_LIVE", raising=False)
    b = OFF._bench()
    monkeypatch.setattr(b, "_dtt", lambda: pytest.fail("reached KEAP without NOS_LIVE"))
    assert b.main(["--seed", "--domain", "d1"]) == 2


def _wire(*slices, error=None):
    whole = OFF._got(text=" ".join(s["text"] for s in slices))
    return whole | {"per_turn": list(slices), "error": error, "renders": [r for s in slices for r in s["renders"]]}


def test_a_broken_wire_is_reported_even_after_a_failed_turn():
    case = {"id": "c", "turns": [{"say": f"q{i}", "checks": {"not_blank": True}} for i in range(3)]}
    failed, turns = OFF._bench().judge(case, _wire(OFF._got(text=""), error="OSError: x"), 0)
    assert [t["status"] for t in turns] == ["fail", "not_reached", "not_reached"]
    assert failed == ["turn 0: not_blank", "error: OSError: x"]


def test_a_got_without_per_turn_is_its_own_single_turn():
    b = OFF._bench()
    assert b.score({"prompt": "q", "checks": {"not_blank": True}}, OFF._got(text="yes"), 0) == []
    assert b.score({"prompt": "q", "checks": {"not_blank": True}}, OFF._got(text=""), 0) == ["not_blank"]


def test_a_number_is_contained_as_a_number_not_a_substring():
    b = OFF._bench()
    assert b.check("text_contains", "9", OFF._got(text="There are 9 rows."), 0)
    assert not b.check("text_contains", "9", OFF._got(text="There are 19 rows."), 0)
    assert not b.check("text_contains", "9", OFF._got(text="It is 9.5."), 0)
    assert b.check("text_contains", "CANARY-27", OFF._got(text="It says CANARY-27."), 0)


def test_a_majority_pass_reports_a_passing_run(tmp_path, monkeypatch):
    case = {"id": "c", "turns": [{"say": "q0", "checks": {"not_blank": True}}, {"say": "q1", "checks": {"not_blank": True}}]}
    p = tmp_path / "cases.yml"
    p.write_text(yaml.safe_dump([case]), encoding="utf-8")
    b, ok, bad = OFF._bench(), _wire(OFF._got(text="a"), OFF._got(text="b")), _wire(OFF._got(text=""))
    gots = iter([bad, ok, ok])
    monkeypatch.setattr(b, "run_case", lambda *a: next(gots))
    out = tmp_path / "run.json"
    assert b.main(["--sock", "x", "--offline", "--cases", str(p), "--out", str(out), "--repeat", "3"]) == 0
    r = json.loads(out.read_text())["cases"][0]
    assert r["pass"] and r["passes"] == 2 and r["depth"] == 2 and [t["status"] for t in r["turns"]] == ["pass", "pass"]


def test_oneshot_names_the_turn_checks_it_cannot_judge():
    poc = _load("oneshot_poc", "tools/oneshot-poc.py")
    failed, nt = poc.score(CASE, [{"tool": "query_rows", "args": {"table": "t", "where": NEXT}}])
    assert "turn 0: query_uses" in nt and "turn 1: chart_source" in nt and "turn 2: query_uses" in nt


class RefKeap(FakeKeap):
    """Rows a parent table holds come back on GET, so the seeder can map a rowRef label to its row id."""

    def __init__(self):
        super().__init__()
        self.rows = {}

    def req(self, method, path, body=None):
        if method == "GET":
            tid = path.split("/")[3]
            return 200, {"data": {"rows": [{"id": f"{tid}-r{i}", "values": v} for i, v in enumerate(self.rows.get(tid, []))]}}
        st, r = super().req(method, path, body)
        if path.endswith("/rows"):
            self.rows.setdefault(path.split("/")[3], []).append(body["values"])
        return st, r


def test_seed_domain_creates_a_parent_first_and_maps_its_row_refs(tmp_path, monkeypatch):
    root = _domain(tmp_path)
    (root / "domains/d1/tables/a-lines.table.yml").write_text(yaml.safe_dump({
        "title": "lines", "driver": "libsql", "visibility": "shared", "anchors": [],
        "schema": {"columns": [{"key": "item", "label": "Item", "kind": "text"},
                               {"key": "part", "label": "Part", "kind": "rowRef", "refTable": "parts", "refDisplay": "name"}]},
        "rows": [{"item": "x", "part": "nut"}]}), encoding="utf-8")
    monkeypatch.setenv("NOS_ASSAY_DIR", str(root))
    monkeypatch.setenv("NOS_LIVE", "1")
    monkeypatch.syspath_prepend(str(REPO / "tools"))  # keap_api, as when run as a script
    b, keap = OFF._bench(), RefKeap()
    monkeypatch.setattr(b, "_dtt", lambda: keap)
    assert b.main(["--seed", "--domain", "d1"]) == 0
    creates = [p for p in keap.posts if p[1] == "/api/tables"]
    assert [c[2]["title"] for c in creates] == ["parts", "lines"]
    assert creates[1][2]["schema"]["columns"][1]["refTable"] == "new-1"
    assert keap.rows["new-4"] == [{"item": "x", "part": "new-1-r1"}]
