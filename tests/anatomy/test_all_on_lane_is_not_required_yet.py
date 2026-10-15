"""The all-on install lane runs on PRs into master and never blocks, until measured once.

Ruling 2026-10-15: all-on becomes required for dev->master only after one measured
non-blocking run. Making it required later edits this gate, so the change is visible.
"""
from __future__ import annotations

import pathlib

import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _wf() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_the_workflow_can_be_dispatched() -> None:
    assert "workflow_dispatch" in _wf()["on"], "ci.yml has no workflow_dispatch; all-on cannot be run by hand"


def test_all_on_runs_on_master_prs_and_dispatch_only() -> None:
    job = _wf()["jobs"].get("all-on")
    assert job, "ci.yml has no all-on job"
    cond = " ".join(str(job.get("if", "")).split())
    assert cond == ("github.event_name == 'workflow_dispatch' || "
                    "(github.event_name == 'pull_request' && github.base_ref == 'master')"), cond


def test_all_on_installs_the_all_on_profile() -> None:
    runs = [str(s.get("run", "")) for s in _wf()["jobs"]["all-on"]["steps"]]
    converge = [r for r in runs if "ansible-playbook main.yml" in r and "--syntax-check" not in r]
    assert converge and "-e @profiles/all-on.yml" in converge[0], "all-on lane does not install profiles/all-on.yml"
    assert "-e @profiles/core.yml" not in converge[0], "all-on lane narrows itself to core"


def test_all_on_is_not_required_yet() -> None:
    jobs = _wf()["jobs"]
    assert jobs["all-on"].get("continue-on-error") is True, "all-on blocks before one measured run"
    assert jobs["all-on"].get("timeout-minutes"), "all-on has no timeout; a hang pins a runner for 6h"
    gated = [n for n, j in jobs.items() if "all-on" in (j.get("needs") or [])]
    assert not gated, f"jobs wait on all-on, so it blocks through them: {gated}"
