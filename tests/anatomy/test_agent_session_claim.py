"""One pulse run, many agents — and only the first may BE the run.

MEASURED 2026-09-23. On 2026-08-29 `tools/run-agent.sh` began adopting
PULSE_RUN_ID as the agent session uuid so "the run and the session are one
row". True for a job that runs one agent. The invoice vision pipeline runs two
agents per page over six pages in ONE run, so eleven of its twelve calls died
on `UNIQUE constraint failed: agent_sessions.uuid` — and `loop:vision-bench`
reported the failure as "is qwen2.5vl:7b pulled and ollama armed?", which sent
every reader at the wrong thing while the loop stayed red for weeks.

This gate EXECUTES the claim rather than reading the script's prose about it:
the second claim on a run id must fail, or the crash comes back.
"""
from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CLAIM = REPO / "files" / "anatomy" / "scripts" / "agent-session-claim.sh"
RUNNER = REPO / "tools" / "run-agent.sh"

if os.name != "posix":
    pytest.skip("bash claim probe is POSIX-only", allow_module_level=True)


def _claim(run_id: str, home: pathlib.Path) -> int:
    return subprocess.run(
        ["bash", "-c", f'source "{CLAIM}"; nos_agent_session_claim "{run_id}"'],
        env={**os.environ, "NOS_AGENT_SESSION_CLAIM_DIR": str(home)},
        capture_output=True, text=True).returncode


def test_the_first_agent_of_a_run_claims_it(tmp_path):
    assert _claim("11111111-1111-4111-8111-111111111111", tmp_path) == 0


def test_the_second_agent_of_the_same_run_does_not(tmp_path):
    """The defect, as the thing that must stay false."""
    run = "22222222-2222-4222-8222-222222222222"
    assert _claim(run, tmp_path) == 0
    assert _claim(run, tmp_path) != 0, "two agents both claimed one run uuid"
    assert _claim(run, tmp_path) != 0


def test_a_different_run_is_not_blocked_by_an_earlier_one(tmp_path):
    assert _claim("33333333-3333-4333-8333-333333333333", tmp_path) == 0
    assert _claim("44444444-4444-4444-8444-444444444444", tmp_path) == 0


def test_an_empty_run_id_claims_nothing(tmp_path):
    assert _claim("", tmp_path) != 0
    assert list(tmp_path.iterdir()) == []


def test_the_runner_links_every_session_to_its_run():
    """Self-allocating a uuid is only safe because trigger-id still carries the
    link — without it the later sessions of a run would be orphans."""
    body = RUNNER.read_text(encoding="utf-8")
    assert "agent-session-claim.sh" in body, "run-agent.sh no longer sources the claim"
    assert "nos_agent_session_claim" in body, "run-agent.sh no longer claims"
    assert "--trigger-id=$PULSE_RUN_ID" in body, \
        "a self-allocated session must still name the run it came from"
