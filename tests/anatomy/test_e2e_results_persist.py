"""The estate e2e verdicts are written down, and a reader reads them back.

WHY. tests/e2e/estate runs ~350 probes against the live estate and, until this
gate, its verdicts lived only in the terminal: "e2e 1 fail (jellyfin oidc 400)"
existed as a chat message. ssot/doctrine/gates.md — success is written by a
reader, not by the code that did the work. tools/nos-smoke.py already appends
its runs to ~/.nos/events as JSONL; the e2e hook mirrors that shape into
~/.nos/e2e/results.jsonl and tools/e2e-status.py reads the LAST run back.

Pinned here, offline: the hook writes one line per probe with the agreed keys,
derives the service from the three param-id shapes the suite uses, is silent
when NOS_E2E_RESULTS is the empty string; the reader prints UNKNOWN without a
file and the counts with one. Never runs tests/e2e (that hits the estate).
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CONFTEST = REPO / "tests/e2e/estate/conftest.py"
READER = REPO / "tools/e2e-status.py"


def _conftest():
    spec = importlib.util.spec_from_file_location("estate_conftest", CONFTEST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(nodeid, outcome="passed", when="call", duration=0.25):
    return SimpleNamespace(nodeid=nodeid, outcome=outcome, when=when, duration=duration)


def test_the_hook_appends_one_line_per_verdict(tmp_path, monkeypatch):
    out = tmp_path / "results.jsonl"
    monkeypatch.setenv("NOS_E2E_RESULTS", str(out))
    cf = _conftest()
    for r in (
        _report("tests/e2e/estate/test_config_journeys.py::test_native[jellyfin]", "failed"),
        _report("tests/e2e/estate/test_config_journeys.py::test_native[jellyfin]", when="setup"),
        _report("tests/e2e/estate/test_effect_probes.py::test_probe[grafana:dashboard]"),
        _report("tests/e2e/estate/test_rbac_users.py::test_matrix[alice-t1:nextcloud-t3]", "skipped"),
        _report("tests/e2e/estate/test_table_anchors_resolve.py::test_anchors", "failed", when="setup"),
    ):
        cf.pytest_runtest_logreport(r)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 4, "one line per verdict: call phase, plus a setup that did not pass"
    assert set(rows[0]) == {"ts", "run_id", "type", "nodeid", "outcome", "duration_ms", "service"}
    assert rows[0]["type"] == "e2e_result" and rows[0]["outcome"] == "failed"
    assert len({r["run_id"] for r in rows}) == 1 and rows[0]["run_id"].startswith("e2e_")
    assert [r["service"] for r in rows] == ["jellyfin", "grafana", "nextcloud", None]
    assert rows[0]["duration_ms"] == 250


def test_the_hook_is_off_when_the_override_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_E2E_RESULTS", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    _conftest().pytest_runtest_logreport(_report("tests/e2e/estate/test_x.py::t[svc]"))
    assert not list(tmp_path.rglob("*.jsonl"))


def _run_reader(env_path: str) -> str:
    env = {**os.environ, "NOS_E2E_RESULTS": env_path}
    out = subprocess.run([sys.executable, str(READER)], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_the_reader_says_unknown_without_a_file(tmp_path):
    assert "UNKNOWN" in _run_reader(str(tmp_path / "absent.jsonl"))


def test_the_reader_counts_the_last_run(tmp_path):
    f = tmp_path / "results.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in (
        {"ts": "2026-10-01T00:00:00Z", "run_id": "e2e_old", "type": "e2e_result",
         "nodeid": "a.py::t[old]", "outcome": "failed", "duration_ms": 1, "service": "old"},
        {"ts": "2026-10-09T00:00:00Z", "run_id": "e2e_new", "type": "e2e_result",
         "nodeid": "a.py::t[jellyfin]", "outcome": "failed", "duration_ms": 1, "service": "jellyfin"},
        {"ts": "2026-10-09T00:00:00Z", "run_id": "e2e_new", "type": "e2e_result",
         "nodeid": "a.py::t[grafana]", "outcome": "passed", "duration_ms": 1, "service": "grafana"},
    )) + "\n")
    text = _run_reader(str(f))
    assert "e2e_new" in text and "e2e_old" not in text, "the LAST run, not the file"
    assert "1 failed" in text and "1 passed" in text
    assert "a.py::t[jellyfin]" in text and "a.py::t[old]" not in text


@pytest.mark.parametrize("flag", ["--json"])
def test_the_reader_json_shape(tmp_path, flag):
    env = {**os.environ, "NOS_E2E_RESULTS": str(tmp_path / "absent.jsonl")}
    out = subprocess.run([sys.executable, str(READER), flag], env=env, capture_output=True, text=True)
    assert out.returncode == 0
    assert json.loads(out.stdout)["sources_missing"]
