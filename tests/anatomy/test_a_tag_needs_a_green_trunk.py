"""Anatomy CI gate — a release tag cannot be pushed onto a red trunk.

Fee 39: master was red from 2026-07-16 through BOTH beta tags (v0.10, v0.11).
The release checklist said "check CI"; nothing enforced it, and prose is what
already failed twice. The pre-push hook is the one chokepoint every tag push
passes, so the guard lives there.

Behavioral, not grep: each test RUNS the hook as a subprocess with a stub `gh`
(via NOS_TAG_GATE_GH) and asserts the exit code. Fail CLOSED is the contract —
no gh, no runs, or nothing green all refuse; UNKNOWN is never green.
"""

from __future__ import annotations

import json
import pathlib
import stat
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "tools" / "git-hooks" / "pre-push"

#: The recorded shape of fee 39: the master series at v0.11-beta — failures
#: with an old success underneath. The hook must refuse exactly this.
V011_SERIES = [{"name": "CI", "status": "completed", "conclusion": "failure"}] * 9 + [
    {"name": "CI", "status": "completed", "conclusion": "success"}]


def _run(tmp: pathlib.Path, runs, ref="refs/tags/v9.9-test", env=None,
         stub_body=None) -> subprocess.CompletedProcess:
    stub = tmp / "gh"
    stub.write_text(stub_body or f"#!/bin/sh\necho '{json.dumps(runs)}'\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()
    line = f"{ref} {sha} {ref} {'0' * 40}\n"
    return subprocess.run(["bash", str(HOOK), "origin", "url"], input=line,
                          cwd=REPO, capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp),
                               "NOS_TAG_GATE_GH": str(stub), **(env or {})})


def test_the_recorded_v011_series_is_refused(tmp_path):
    """Retro-verification built in: replay the exact history the checklist
    waved through, and assert the hook would have stopped it."""
    r = _run(tmp_path, V011_SERIES)
    assert r.returncode == 1, "the v0.11-beta red series was let through again"
    assert "RED: CI" in r.stderr


def test_all_green_passes(tmp_path):
    r = _run(tmp_path, [{"name": "CI", "status": "completed",
                         "conclusion": "success"}])
    assert r.returncode == 0, f"a green commit was refused:\n{r.stderr}"


def test_no_runs_is_not_green(tmp_path):
    r = _run(tmp_path, [])
    assert r.returncode == 1, "a commit with NO CI run was tagged — absence read as success"
    assert "UNKNOWN" in r.stderr


def test_pending_only_is_not_green(tmp_path):
    r = _run(tmp_path, [{"name": "CI", "status": "in_progress", "conclusion": None}])
    assert r.returncode == 1
    assert "pending is not green" in r.stderr


def test_a_broken_gh_fails_closed(tmp_path):
    r = _run(tmp_path, None, stub_body="#!/bin/sh\nexit 1\n")
    assert r.returncode == 1, "gh broke and the tag went through — fail OPEN"


def test_the_bypass_is_loud(tmp_path):
    r = _run(tmp_path, V011_SERIES, env={"NOS_TAG_RED_OK": "1"})
    assert r.returncode == 0
    assert "bypassed" in r.stderr, "the bypass left no trace in the push output"


def test_branch_pushes_are_untouched(tmp_path):
    """The tag gate must not spend gh calls or verdicts on ordinary pushes."""
    r = _run(tmp_path, V011_SERIES, ref="refs/heads/feature-x")
    assert r.returncode == 0, f"a plain branch push was refused:\n{r.stderr}"
