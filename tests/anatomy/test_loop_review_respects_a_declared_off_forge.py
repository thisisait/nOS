"""Anatomy CI gate — a forge declared off is a decision, not a nightly failure.

MEASURED 2026-09-02: install_gitlab false stopped the GitLab container (the new
stop discipline working), and loop:review then exited 2 every night — a job
correctly red for a condition the operator had deliberately chosen. Operator
ruling the same day: gate on the flag. Unreachable while the flag is TRUE stays
rc=2 — that is a real failure, and this gate must never blur the two.

Runs the SCRIPT and reads its exit code — not the source text.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _resolved_flag() -> str:
    for f in (REPO / "config.yml", REPO / "default.config.yml"):
        if not f.is_file():
            continue
        m = re.search(r"^install_gitlab:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip().lower()
    return ""


def test_a_declared_off_forge_is_a_clean_skip():
    if _resolved_flag() != "false":
        pytest.skip("install_gitlab resolves true here — the off branch cannot "
                    "be exercised without lying about the config")
    run = subprocess.run(["python3", str(REPO / "tools/loop-review.py")],
                         cwd=REPO, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, (
        f"install_gitlab is false and loop-review exited {run.returncode}:\n"
        f"{run.stderr[-800:]}\nA deliberate off must not spend the error path")
    assert "install_gitlab is false" in run.stdout, (
        "the skip does not name the flag, so an operator reading the run log "
        "cannot tell a decision from a silent no-op")
