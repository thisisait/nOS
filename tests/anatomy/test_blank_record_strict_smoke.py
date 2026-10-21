"""Gate: a nos-smoke --strict run after a blank lands in that blank's record.

10-17: the operator ran nos-smoke --strict 32/32 AFTER the converge; the record
kept smoke_strict null and estate-status said 'release gate unmet' for a met
gate. Runs nos-smoke's main() with a tmp HOME and fake probes (nothing is asked
over the network) and reads the BLANK axis back through estate-status.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(home: Path, finished_hours_ago: float | None) -> None:
    (home / ".nos").mkdir()
    (home / ".nos/blank-runs.jsonl").write_text(json.dumps(
        {"started": _ts((finished_hours_ago or 0) + 1),
         "finished": None if finished_hours_ago is None else _ts(finished_hours_ago),
         "nos_commit": "x", "failed": False, "smoke_strict": None}) + "\n")


def _smoke(home: Path, monkeypatch, argv: list, red: bool = False):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.syspath_prepend(str(REPO / "tools"))
    mod = _load("nos_smoke_gate", "nos-smoke.py")
    entries = [{"id": f"svc{i}", "url": f"http://127.0.0.1:1/{i}", "expect": [200], "tier": 1} for i in range(3)]
    monkeypatch.setattr(mod, "load_vars", lambda *a, **k: {})
    monkeypatch.setattr(mod, "build_catalog", lambda v: entries)
    monkeypatch.setattr(mod, "resolve_tester_password", lambda *a: None)
    monkeypatch.setattr(mod, "probe", lambda e, **k: mod.ProbeResult(e, 200, 1, None, not (red and e["id"] == "svc0")))
    monkeypatch.setattr(sys, "argv", ["nos-smoke.py", "--no-jsonl", *argv])
    return mod.main()


def _blank_line(home: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    mod = _load("estate_status_gate", "estate-status.py")
    res = mod.Result()
    mod.axis_blank(res)
    (line,) = [x for x in res.lines if x.axis == "blank"]
    return mod, line


def test_a_strict_smoke_after_a_blank_meets_the_release_gate(tmp_path, monkeypatch, capsys):
    _record(tmp_path, finished_hours_ago=2)
    assert _smoke(tmp_path, monkeypatch, ["--strict"]) == 0
    smoke = json.loads((tmp_path / ".nos/blank-runs.jsonl").read_text().splitlines()[-1])["smoke_strict"]
    assert smoke and (smoke["ok"], smoke["total"], smoke["failed"]) == (3, 3, []) and smoke["at"], smoke
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.OK and "release gate met" in line.detail and "3/3" in line.detail, line


def test_a_red_strict_smoke_is_recorded_and_unmet(tmp_path, monkeypatch):
    _record(tmp_path, finished_hours_ago=2)
    assert _smoke(tmp_path, monkeypatch, ["--strict"], red=True) == 1
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE and "2/3" in line.detail and "svc0" in line.detail, line
    assert "release gate unmet" in line.detail


def test_a_null_strict_record_reads_unmet(tmp_path, monkeypatch):
    _record(tmp_path, finished_hours_ago=2)
    mod, line = _blank_line(tmp_path, monkeypatch)
    assert line.state == mod.DISAGREE and "release gate unmet" in line.detail, line


@pytest.mark.parametrize("finished, argv, why", [
    (30, ["--strict"], "older than 24h"),        # the window (operator's to tune)
    (None, ["--strict"], "still open"),          # post-smoke inside the blank writes that one
    (2, [], "not --strict"),
    (2, ["--strict", "--tier", "1"], "filtered"),  # a partial run is not release evidence
], ids=["stale", "open", "lax", "filtered"])
def test_a_run_that_does_not_count_says_why_and_leaves_the_record(tmp_path, monkeypatch, capsys,
                                                                   finished, argv, why):
    _record(tmp_path, finished_hours_ago=finished)
    before = (tmp_path / ".nos/blank-runs.jsonl").read_text()
    _smoke(tmp_path, monkeypatch, argv)
    assert (tmp_path / ".nos/blank-runs.jsonl").read_text() == before
    if argv:  # a plain run is not about the record: it stays quiet
        err = capsys.readouterr().err
        assert "not recorded" in err and why in err, err
