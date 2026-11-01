"""nOS.app's decoder gate has a macOS CI lane that declares swift, and it never blocks until green once.

test_nos_app_reads_state.py skips without swift, so before this lane it ran only on the
operator's Mac. The lane declares swift in NOS_TEST_PROVIDES, so a runner without it aborts
instead of skipping. Making it required later edits this gate, so the change is visible.
"""
from __future__ import annotations

import pathlib

import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _job() -> dict:
    job = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"].get("nos-app")
    assert job, "ci.yml has no nos-app job; the app's decoder gate runs nowhere but the operator's Mac"
    return job


def test_the_lane_runs_the_decoder_gate_on_macos_with_swift_declared() -> None:
    job = _job()
    assert str(job.get("runs-on", "")).startswith("macos-"), "SwiftUI builds on macOS only"
    declared = {t.strip() for t in str((job.get("env") or {}).get("NOS_TEST_PROVIDES", "")).split(",")}
    assert "swift" in declared, "swift is not declared, so a runner without it skips the gate green"
    runs = "\n".join(str(s.get("run", "")) for s in job.get("steps") or [])
    assert "tests/anatomy/test_nos_app_reads_state.py" in runs, "the lane does not run the decoder gate"


def test_the_lane_is_not_required_yet() -> None:
    job = _job()
    assert job.get("continue-on-error") is True, "the nos-app lane blocks before one green run"
    assert job.get("timeout-minutes"), "the nos-app lane has no timeout; a hang pins a runner for 6h"
