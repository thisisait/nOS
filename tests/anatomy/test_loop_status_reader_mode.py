"""`tools/loop-status.py --loop <id> --since <date>` — one loop's record, per source.

The default report answers "which weakness sources produce proposals"; it did
not answer "did loop X run, and what came of it". Measured 2026-10-21: the
ledger held 32 baseline verdicts and 0 proposals, and the loops' pulse runs were
read only by red-status, so "news-scout never ran" and "news-scout is not even
registered (install_loops off)" looked the same — an empty answer. This gate
pins the reader mode: the ledger for SERE, pulse_runs + held jobs for a manifest
loop, and `registered: false` (never an empty history) when no job exists.

Every database here is a scratch wing.db built from the ledger's own DDL; the
reader's WING_DB is pointed at it explicitly.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "loop-status.py"
D = "2026-10-01"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def loop():
    return _load(TOOL, "_loop_status_mode")


def _scratch_db(path: Path) -> sqlite3.Connection:
    sys.path.insert(0, str(REPO / "files/anatomy/bone"))
    try:
        ledger = _load(REPO / "files/anatomy/bone/ledger.py", "_ledger_scratch")
    finally:
        sys.path.pop(0)
    conn = sqlite3.connect(path)
    ledger.ensure_schema(conn)
    ddl = (REPO / "files/anatomy/wing/db/schema-extensions.sql").read_text(encoding="utf-8")
    for table in ("pulse_jobs", "pulse_runs"):
        conn.execute(re.search(rf"CREATE TABLE IF NOT EXISTS {table} \(.*?\n\);", ddl, re.S).group(0))
    return conn


def _run(loop, monkeypatch, capsys, *argv) -> dict:
    monkeypatch.setattr(sys, "argv", ["loop-status.py", *argv, "--json"])
    try:
        rc = loop.main()
    except SystemExit as exc:      # argparse refusing the flags
        pytest.fail(f"loop-status refused {argv}: no --loop/--since reader mode (exit {exc.code})")
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def _verdict(conn, n, gate_set, result, at):
    conn.execute("INSERT INTO loop_verdicts (uuid, gate_set, result, actor, tree_sha, "
                 "evidence, created_at) VALUES (?,?,?,'engine:judge-runner','t','{}',?)",
                 (f"v{n}", gate_set, result, at))


def _judge_run(conn, n, gate_set, outcome, status, at, reason=""):
    conn.execute("INSERT INTO loop_judge_runs (uuid, gate_set, judge_name, argv, status, "
                 "started_at, exit_code, work_count, min_work, outcome, reason) "
                 "VALUES (?,?,?,'[]',?,?,?,5,1,?,?)",
                 (f"j{n}", gate_set, f"judge{n}", status, at,
                  0 if outcome == "pass" else 1, outcome, reason))


def test_sere_reports_verdicts_judge_runs_and_awaiting(loop, tmp_path, monkeypatch, capsys):
    db = tmp_path / "wing.db"
    with _scratch_db(db) as conn:
        _verdict(conn, 1, "baseline", "pass", "2026-09-20 06:00:00")   # before --since
        _verdict(conn, 2, "baseline", "pass", "2026-10-02 06:00:00")
        _verdict(conn, 3, "baseline", "pass", "2026-10-03 06:00:00")
        _verdict(conn, 4, "pin-bump", "fail", "2026-10-04 06:00:00")
        _judge_run(conn, 1, "baseline", "pass", "exited", "2026-10-02 06:00:00")
        _judge_run(conn, 2, "pin-bump", "fail", "exited", "2026-10-04 06:00:00", "pytest red")
        _judge_run(conn, 3, "pin-bump", None, "crashed", "2026-10-04 06:01:00")
        _judge_run(conn, 4, "pin-bump", "fail", "exited", "2026-09-01 06:00:00")  # before --since
        conn.execute("INSERT INTO loop_proposals (uuid, fingerprint, weakness_id, intent_class, "
                     "gate_set, target_paths, tree_sha, proposer_id) VALUES "
                     "('pppp1111','fp','rem:REM-1','config-fix','pin-bump','[]','c','agent:x')")
    monkeypatch.setattr(loop, "WING_DB", db)
    monkeypatch.setattr(loop, "_readiness", lambda ids: {"status": "ok", "held": {}}, raising=False)

    out = _run(loop, monkeypatch, capsys, "--loop", "sere", "--since", D)

    ledger = out["ledger"]
    assert ledger["verdicts"] == {"baseline": {"pass": 2}, "pin-bump": {"fail": 1}}, (
        f"verdicts since {D} by gate_set/result are wrong: {ledger['verdicts']}")
    not_passed = {r["judge_name"]: r for r in ledger["judge_runs_not_passed"]}
    assert set(not_passed) == {"judge2", "judge3"}, (
        f"judge runs since {D} that did not pass: {sorted(not_passed)}")
    assert not_passed["judge2"]["reason"] == "pytest red"
    assert ledger["awaiting"] == {"unjudged": 1}, (
        f"awaiting states lost the unjudged proposal: {ledger['awaiting']}")


def test_a_manifest_loop_reports_its_pulse_runs_and_held_jobs(loop, tmp_path, monkeypatch, capsys):
    db = tmp_path / "wing.db"
    with _scratch_db(db) as conn:
        conn.execute("INSERT INTO pulse_jobs (id, plugin_name, job_name, command, schedule) "
                     "VALUES ('loop:news-scout','loop','news-scout','x','0 7 * * *')")
        rows = [("r0", "2026-09-01T07:00:00", 1, "", "old"),       # before --since
                ("r1", "2026-10-02T07:00:00", 0, "", ""),
                ("r2", "2026-10-03T07:00:00", 1, "", "Traceback\nboom"),
                ("r3", "2026-10-04T07:00:00", 78, "HELD: claude CLI missing", "")]
        conn.executemany("INSERT INTO pulse_runs (run_id, job_id, fired_at, exit_code, "
                         "stdout_tail, stderr_tail) VALUES (?, 'loop:news-scout', ?, ?, ?, ?)", rows)
    monkeypatch.setattr(loop, "WING_DB", db)
    held = {"loop:news-scout": ["claude CLI missing"]}
    monkeypatch.setattr(loop, "_readiness", lambda ids: {"status": "ok", "held": held}, raising=False)

    out = _run(loop, monkeypatch, capsys, "--loop", "news-scout", "--since", D)

    pulse = out["pulse"]
    assert pulse["registered"] is True
    assert pulse["count"] == 3, f"runs since {D}: {pulse['count']}"
    assert pulse["exit_codes"] == {"0": 1, "1": 1, "78": 1}
    assert pulse["last_fired"] == "2026-10-04T07:00:00"
    assert [f["stderr_tail"] for f in pulse["failures"]] == ["Traceback\nboom"], (
        "a failed run must carry its stderr tail; a held run (78) is not a failure")
    assert pulse["held"] == [{"job_id": "loop:news-scout", "fired_at": "2026-10-04T07:00:00",
                              "needs": ["claude CLI missing"]}]
    assert out["readiness"]["held"] == {"loop:news-scout": ["claude CLI missing"]}
    assert "ledger" not in out, "a manifest loop has no ledger; reporting SERE's would mislead"


def test_no_registered_job_is_said_never_an_empty_history(loop, tmp_path, monkeypatch, capsys):
    db = tmp_path / "wing.db"
    _scratch_db(db).close()
    monkeypatch.setattr(loop, "WING_DB", db)
    monkeypatch.setattr(loop, "_readiness", lambda ids: {"status": "ok", "held": {}}, raising=False)

    out = _run(loop, monkeypatch, capsys, "--loop", "news-scout")

    assert out["pulse"] == {"registered": False,
                            "said": "no loop job registered (install_loops?)"}, (
        f"an unregistered loop read as {out['pulse']} — an empty run history "
        f"would say 'never ran' when the truth is 'not scheduled'")


def test_every_source_is_unknown_when_unreadable(loop, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loop, "WING_DB", tmp_path / "absent.db")

    def boom(*_a, **_k):
        raise RuntimeError("judge would not load")

    monkeypatch.setattr(loop, "_load_tool", boom, raising=False)
    out = _run(loop, monkeypatch, capsys, "--loop", "sere")

    for source in ("ledger", "pulse", "readiness"):
        assert out[source]["status"] == "UNKNOWN", f"{source} read as {out[source]}, not UNKNOWN"
        assert out[source]["why"], f"{source} is UNKNOWN without saying why"


def test_the_readiness_source_asks_the_one_judge(loop):
    """No host read: the judge is handed an empty config and a bare host."""
    assert hasattr(loop, "_readiness"), "loop-status has no job_readiness source"
    host = {"claude": None, "ollama_models": set(), "anthropic_key": False}
    got = loop._readiness(["loop:vision-bench"], cfg={}, host=host)
    assert got["status"] == "ok"
    assert got["held"].get("loop:vision-bench"), (
        f"vision-bench declares needs a bare host lacks, yet reads as ready: {got}")


def test_an_unknown_loop_is_named_not_answered(loop, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(loop, "WING_DB", tmp_path / "absent.db")
    out = _run(loop, monkeypatch, capsys, "--loop", "no-such-loop")
    assert "unknown loop" in out["error"] and "news-scout" in out["known"]
