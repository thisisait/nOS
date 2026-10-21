"""tools/bench-compare.py pairs two iris-bench --out runs case by case and says what differs.

A claim like "the cortex plan path beats plain tool calling" is only measured when the two runs
differ on one axis (plan path, model digest, commit, primer...) and the paired flips are counted
(exact McNemar). Two runs that differ on no axis are a repeatability check: any flip means the
bench is not deterministic at that config.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "bench-compare.py"

spec = importlib.util.spec_from_file_location("bench_compare", TOOL)
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)


def _run(passes: dict, plan="tools", digest="sha256:aa", commit="c1", no_data=()) -> dict:
    return {"plan_path": plan, "primer_sha256": None, "grammar_sha256": None, "registry_hash": None,
            "provenance": {"nos_commit": commit, "models": [{"role": "m", "name": "qwen3:14b", "digest": digest}]},
            "cases": [{"id": k, "pass": v, "no_data": k in no_data} for k, v in passes.items()]}


def test_mcnemar_exact_is_two_sided_and_capped():
    assert bc.mcnemar(0, 0) == 1.0
    assert bc.mcnemar(0, 6) == 2 * 0.5 ** 6
    assert abs(bc.mcnemar(1, 9) - 0.021484375) < 1e-12
    assert bc.mcnemar(5, 5) == 1.0


def test_the_axes_name_what_the_two_runs_differ_on():
    a, b = _run({"x": True}), _run({"x": True}, plan="cortex", digest="sha256:bb")
    assert bc.axes(a, b) == ["models", "plan_path"]
    assert bc.axes(a, _run({"x": False})) == []


def test_the_catalogue_and_engine_are_axes_too():
    a, b = _run({"x": True}), _run({"x": True})
    b["catalogue"] = "rich"
    assert bc.axes(a, b) == ["catalogue"]


def test_flips_are_also_counted_per_case_kind():
    a = _run({"c1": False, "c2": False, "k1": True})
    b = _run({"c1": True, "c2": True, "k1": False}, plan="cortex")
    for c, kind in zip(a["cases"] + b["cases"], ["chart", "chart", "kpi"] * 2):
        c["kind"] = kind
    r = bc.compare(a, b)["by_kind"]
    assert (r["chart"]["a_only"], r["chart"]["b_only"]) == (0, 2)
    assert (r["kpi"]["a_only"], r["kpi"]["b_only"]) == (1, 0)


def test_a_no_data_case_on_either_side_is_left_out_not_counted():
    a = _run({"x": True, "y": False, "z": True}, no_data=("z",))
    b = _run({"x": False, "y": True, "z": False, "w": True}, plan="cortex")
    r = bc.compare(a, b)
    assert (r["paired"], r["a_only"], r["b_only"]) == (2, 1, 1)
    assert sorted(r["left_out"]) == ["w", "z"]


def test_one_axis_and_enough_flips_is_a_measured_difference():
    a = _run({f"c{i}": i < 2 for i in range(12)})
    b = _run({f"c{i}": True for i in range(12)}, plan="cortex")
    r = bc.compare(a, b)
    assert (r["a_only"], r["b_only"]) == (0, 10) and r["p"] < 0.05
    assert r["verdict"] == "B better"


def test_two_axes_at_once_is_confounded_whatever_the_flips():
    a = _run({f"c{i}": False for i in range(12)})
    b = _run({f"c{i}": True for i in range(12)}, plan="cortex", digest="sha256:bb")
    assert bc.compare(a, b)["verdict"] == "confounded"


def test_no_axis_and_a_flip_says_the_bench_is_not_repeatable():
    a, b = _run({"x": True, "y": True}), _run({"x": True, "y": False})
    assert bc.compare(a, b)["verdict"] == "not repeatable"
    assert bc.compare(a, a)["verdict"] == "repeatable"


def test_few_flips_are_no_measured_difference():
    a, b = _run({"x": False, "y": True}), _run({"x": True, "y": True}, plan="cortex")
    assert bc.compare(a, b)["verdict"] == "no measured difference"


def test_the_cli_exits_by_verdict(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(_run({"x": True})))
    b.write_text(json.dumps(_run({"x": False})))
    r = subprocess.run([sys.executable, str(TOOL), str(a), str(b)], capture_output=True, text=True)
    assert r.returncode == 1 and "not repeatable" in r.stdout, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(TOOL), str(a), str(a), "--json"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["verdict"] == "repeatable", r.stdout + r.stderr
