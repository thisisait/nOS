"""--rescore re-judges a saved iris-bench run offline: a plan that means the expected one passes.

Night bench 2026-10-18 (cortex, qwen3.5:9b): 76/284 cases failed only pipeline_equals_expected
while the thalamus ran the right query. Two of them are the fixture below, trimmed from
~/iris-bench-local/night2-cortex/std-{crm,accounting}.json: `limit=1` on a get that is counted,
and a chart's `y` the mapper fills from the aggregate anyway. A different filter value still fails.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib

import yaml

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools/iris-bench.py"
DEALS = {"id": "ba6832e2-4a33-4e67-9b4e-983b20423264", "said": "assay-deals", "title": "assay-deals"}
INVOICES = {"id": "9460d363-1629-4e13-bc65-bb6e6c5f10f3", "said": "assay-invoices", "title": "assay-invoices"}
CASES = [
    {"id": "crm-date-range-deals-close_date-2026-10-15-2026-10-24-en2", "kind": "date-range",
     "prompt": "Count the rows of assay-deals with close_date between 2026-10-15 and 2026-10-24, both days included.",
     "expect_pipeline": ['get(db:assay-deals) | filter(where="close_date between 2026-10-15,2026-10-24")',
                         'get(db:assay-deals) | filter(where="close_date between 2026-10-15,2026-10-24") | aggregate(op=count)'],
     "checks": {"tools_called": ["query_rows"], "text_contains": "8"}},
    {"id": "accounting-chart-invoices-bar-status-amount-en1", "kind": "chart",
     "prompt": "Bar chart of the summed amount per status in assay-invoices.",
     "expect_pipeline": "get(db:assay-invoices) | aggregate(op=sum, by=status, y=amount) | show(kind=chart, chart=bar, x=status)",
     "checks": {"kinds_drawn": ["chart:bar"]}},
]


def _result(case_id, kind, source, table):
    return {"id": case_id, "kind": kind, "turns": [{"index": 0, "status": "fail", "failed": ["pipeline_equals_expected"]}],
            "depth": None, "runs": 1, "passes": 0, "pass": False, "no_data": False, "failed": ["pipeline_equals_expected"],
            "pipeline": {"source": source, "valid": True, "errors": [], "fell_back": False, "fallback": None,
                         "fallback_kind": None, "table": table},
            "plan_checks": ["pipeline_equals_expected", "pipeline_fell_back", "pipeline_valid"]}


def test_rescore_passes_the_same_meaning_and_keeps_a_different_plan_failing(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("iris_bench_rescore", TOOL)
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    cases = tmp_path / "cases.yml"
    cases.write_text(yaml.safe_dump(CASES), encoding="utf-8")
    deals = _result(CASES[0]["id"], "date-range", 'get(db:assay-deals, limit=1) | filter(where="close_date between '
                    '2026-10-15,2026-10-24") | aggregate(op="count")', DEALS)
    chart = _result(CASES[1]["id"], "chart", 'get(db:assay-invoices) | aggregate(by="status", op="sum", y="amount") | '
                    'show(chart="bar", kind="chart", x="status", y="amount")', INVOICES)
    other = copy.deepcopy(deals)
    other["pipeline"]["source"] = other["pipeline"]["source"].replace("2026-10-24", "2026-10-25")
    saved = tmp_path / "std-crm.json"
    run = {"provenance": {"nos_commit": "0" * 40, "argv": ["--cases", str(cases), "--plan", "cortex"], "plan": "cortex"},
           "plan_path": "cortex", "cases": [deals, chart]}
    saved.write_text(json.dumps(run), encoding="utf-8")
    run["cases"] = [other]
    wrong = tmp_path / "std-other.json"
    wrong.write_text(json.dumps(run), encoding="utf-8")

    assert bench.main(["--rescore", str(saved), str(wrong)]) == 0
    out = capsys.readouterr().out
    got = json.loads(saved.with_suffix(".rescored.json").read_text(encoding="utf-8"))
    assert [(r["pass"], r["failed"], r["turns"][0]["status"]) for r in got["cases"]] == [(True, [], "pass")] * 2
    assert got["rescored"]["rejudged"] == ["pipeline_equals_expected"]
    still = json.loads(wrong.with_suffix(".rescored.json").read_text(encoding="utf-8"))["cases"][0]
    assert not still["pass"] and still["failed"] == ["pipeline_equals_expected"]
    assert "0/2 -> 2/2" in out and "0/1 -> 0/1" in out
    assert json.loads(saved.read_text(encoding="utf-8"))["cases"][0]["pass"] is False, "the saved run is never rewritten"
