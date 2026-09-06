"""A printed remedy must be satisfiable by the reader it is printed for.

MEASURED 2026-09-03: all four withheld rows in the live `--gap` were
`alert:*` — evidence is a firing Prometheus alert, `evidence_committed=False`
by design, no repo file behind it — and the single remedy the tool printed was
"Commit it (the nightly scan writes docs/llm/security/ and nobody commits it)".
Committing that directory would have moved none of them. The class was already
named (docs/idea/19-fable-review-2.md §3.3) and nothing carried it to the
tools; this gate does.

The split is one boolean, `Weakness.evidence_committable`: True = a commit can
unblock the row (the default, and what every file-backed source means); False =
the evidence lives outside the repo (alerts, pulse runs) and the row clears
when its source clears — "observable, not proposable", stated where the
operator reads, not two ideas away.

Retro-verified: with `evidence_committable` forced True on an alert weakness,
`test_the_projection_splits_the_two_reasons` fails on the projection row and
the alert-source test fails on the constructed weakness.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
READER = REPO / "tools" / "loop-status.py"


def _weaknesses():
    sys.path.insert(0, str(BONE))
    try:
        spec = importlib.util.spec_from_file_location("_wk_gate", BONE / "weaknesses.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_wk_gate"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(BONE))


def test_alert_weaknesses_declare_uncommittable_evidence(monkeypatch):
    """Built from a served payload, not from reading the source's prose."""
    mod = _weaknesses()
    payload = {"status": "success", "data": {"alerts": [{
        "state": "firing",
        "labels": {"alertname": "NosCriticalCveFoundCritical",
                   "severity": "critical", "service": "gitea"},
        "annotations": {"summary": "x"},
        "activeAt": "2026-09-03T00:00:00Z", "value": "1",
    }]}}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda req, timeout=5: _Resp(json.dumps(payload).encode()))
    report = mod._source_prometheus_alerts(set())
    assert report.weaknesses, "the fixture alert produced no weakness"
    for w in report.weaknesses:
        assert w.evidence_committed is False
        assert w.evidence_committable is False, (
            f"{w.weakness_id}: an alert's evidence has no repo file behind it; "
            "claiming a commit could unblock it re-creates the misrouted remedy")
        assert w.to_dict()["evidence_committable"] is False


def test_pulse_weaknesses_declare_uncommittable_evidence(tmp_path, monkeypatch):
    db = tmp_path / "wing.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE pulse_jobs (id TEXT, findings_exit_codes TEXT)")
    # The real pulse_runs (and red-status.failing_jobs, now the selection —
    # loop-pulse-runs-poison) carry stdout_tail/duration_ms; carry them here.
    conn.execute(
        "CREATE TABLE pulse_runs (job_id TEXT, exit_code INT, fired_at TEXT,"
        " stderr_tail TEXT, stdout_tail TEXT, duration_ms INT)")
    conn.execute(
        "INSERT INTO pulse_runs VALUES ('cortex:cortex-fs-sync', 7,"
        " '2026-09-03T04:00:00+00:00', 'boom', 'boom', 10)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("WING_DB_PATH", str(db))
    mod = _weaknesses()
    report = mod._source_pulse_runs(set())
    assert report.weaknesses, (
        f"the fixture failed run produced no weakness (status={report.status}, "
        f"detail={report.detail!r})")
    for w in report.weaknesses:
        assert w.evidence_committable is False, (
            f"{w.weakness_id}: a pulse run's evidence is a wing.db row, not a file")


def test_the_projection_splits_the_two_reasons(monkeypatch):
    """`_live_weakness_projection` must carry `commit_unblocks` so the gap
    renderer can branch — one flag for both tools (loop-propose reads the same
    rows)."""
    spec = importlib.util.spec_from_file_location("_ls_gate", READER)
    ls = importlib.util.module_from_spec(spec)
    sys.modules["_ls_gate"] = ls
    spec.loader.exec_module(ls)

    wk = _weaknesses()
    report = wk.SourceReport(
        name="t", status=wk.STATUS_OK,
        freshness=wk.Freshness(basis=wk.BASIS_OBSERVED, value="now"),
        weaknesses=[
            wk.Weakness(weakness_id="rem:REM-1", source="t", severity="high",
                        title="file-backed, uncommitted",
                        evidence_committed=False),
            wk.Weakness(weakness_id="alert:X:1", source="t", severity="high",
                        title="live", evidence_committed=False,
                        evidence_committable=False),
        ])
    monkeypatch.setattr(wk, "collect", lambda: [report])
    monkeypatch.setitem(sys.modules, "weaknesses", wk)
    rows, err = ls.live_weaknesses()
    assert err is None, err
    by_id = {r["id"]: r for r in rows}
    assert by_id["rem:REM-1"]["commit_unblocks"] is True
    assert by_id["alert:X:1"]["commit_unblocks"] is False
    assert by_id["alert:X:1"]["proposable"] is False
