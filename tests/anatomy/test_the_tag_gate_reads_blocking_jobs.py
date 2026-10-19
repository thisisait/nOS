"""The tag gate judges only the CI jobs a release depends on.

Measured at the v0.17 cut: the run was red only through continue-on-error
lanes (All-on), and the operator needed the loud bypass. The non-blocking set
is read from the tagged commit's own workflow; a red one is info, a red
blocking job still refuses. Runs the real hook with a stub `gh`.
"""
from __future__ import annotations

import json
import pathlib
import stat
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "tools" / "git-hooks" / "pre-push"
RUNS = [{"databaseId": 7, "name": "CI", "status": "completed", "conclusion": "failure"}]


def _push(tmp: pathlib.Path, jobs) -> subprocess.CompletedProcess:
    (tmp / "list.json").write_text(json.dumps(RUNS))
    (tmp / "view.json").write_text(json.dumps({"jobs": jobs}))
    stub = tmp / "gh"
    stub.write_text(f'#!/bin/sh\n[ "$2" = view ] && cat {tmp}/view.json || cat {tmp}/list.json\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    ref = "refs/tags/v9.9-test"
    py_dir = str(pathlib.Path(sys.executable).resolve().parent)
    return subprocess.run(["bash", str(HOOK), "origin", "url"], input=f"{ref} {sha} {ref} {'0' * 40}\n",
                          cwd=REPO, capture_output=True, text=True, timeout=60,
                          env={"PATH": f"{py_dir}:/usr/bin:/bin", "HOME": str(tmp), "NOS_TAG_GATE_GH": str(stub)})


def test_a_red_non_blocking_job_passes_and_a_red_blocking_job_refuses(tmp_path):
    lint = {"name": "Lint", "conclusion": "success"}
    soft = {"name": "All-on install (ubuntu-24.04)", "conclusion": "failure"}
    mac = {"name": "Integration (macos-14)", "conclusion": "failure"}
    r = _push(tmp_path, [lint, soft, mac])
    assert r.returncode == 0, f"red continue-on-error lanes refused the tag:\n{r.stderr}"
    assert "info: non-blocking job red" in r.stderr and "All-on install" in r.stderr
    r = _push(tmp_path, [dict(lint, conclusion="failure"), soft])
    assert r.returncode == 1, "a red blocking job (Lint) let the tag through"
    verdict = r.stderr.split("RED:")[1].splitlines()[0]
    assert "CI: Lint" in verdict and "All-on" not in verdict, verdict
