"""The macOS install test runs nightly and never blocks, until it has been green once.

Ruling 2026-10-15: red at idempotence, gating nothing, ~26 min on every PR/master push.
Flip continue-on-error and this gate after its first green nightly run.
"""
from __future__ import annotations

import pathlib

import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _wf() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_the_workflow_has_a_nightly_schedule() -> None:
    crons = [c["cron"] for c in _wf()["on"].get("schedule", [])]
    nightly = [c for c in crons if c.split()[2:] == ["*", "*", "*"]]
    assert nightly, f"no daily cron in ci.yml (have {crons}); the macOS lane would never run"


def test_macos_install_runs_on_schedule_only_and_never_blocks() -> None:
    job = _wf()["jobs"]["integration"]
    cond = " ".join(str(job.get("if", "")).split())
    assert cond == "github.event_name == 'schedule'", f"macOS install runs on more than the schedule: {cond!r}"
    assert job.get("continue-on-error") is True, "macOS install blocks CI before it has been green once"
