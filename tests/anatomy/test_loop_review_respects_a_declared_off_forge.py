"""Anatomy CI gate — a forge declared off is a decision WITH A CONSEQUENCE.

MEASURED 2026-09-02: install_gitlab false stopped the GitLab container (the new
stop discipline working), and loop:review then exited 2 every night — a job
correctly red for a condition the operator had deliberately chosen. Operator
ruling the same day: gate on the flag.

THAT RULING'S FIRST IMPLEMENTATION WAS A SILENT SKIP, and the skip was its own
defect. MEASURED 2026-09-03: with GitLab off, loop:drive judged REM-239 and
REM-244 and nothing could land — the SKIP had severed the loop's whole landing
half, invisibly, at exit 0. So a declared-off forge now has a CONSEQUENCE
rather than a hole: the review moves to Gitea, which carries the CI anyway.

This gate pins the new contract by running the SCRIPT (not reading its source):

  1. It ANNOUNCES the Gitea fallback — an operator reading the log can tell a
     decision from a silent no-op (the failure the skip reintroduced).
  2. It NEVER crashes (rc 1). Measured the same day: `driver._forge` raises the
     DRIVER's `Refused`, a different class than loop-review's, so an
     unprovisioned Gitea escaped as an uncaught traceback (rc 1) instead of a
     clean refusal. The fallback must fail CLOSED, not fall over.
  3. Reachable Gitea with nothing open → rc 0. Unprovisioned/unreachable Gitea
     → rc 2, and the refusal names the forge. Both are honest; rc 1 and a
     silent skip are not.
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


def test_a_declared_off_forge_reviews_on_gitea_and_fails_closed():
    if _resolved_flag() != "false":
        pytest.skip("install_gitlab resolves true here — the off branch cannot "
                    "be exercised without lying about the config")
    run = subprocess.run(["python3", str(REPO / "tools/loop-review.py")],
                         cwd=REPO, capture_output=True, text=True, timeout=120)

    assert "reviewing on Gitea" in run.stdout, (
        "a declared-off GitLab no longer announces the Gitea fallback — the "
        "silent-skip hole that severed the loop's landing half is back")

    assert run.returncode in (0, 2), (
        f"loop-review exited {run.returncode} — not the clean 0 (Gitea "
        f"reachable, nothing open) or the fail-closed 2 (Gitea unprovisioned). "
        f"An rc of 1 is an uncaught crash, the exact cross-module Refused bug "
        f"this gate exists to keep fixed:\n{run.stderr[-600:]}")

    if run.returncode == 2:
        assert "gitea" in run.stderr.lower(), (
            "the fail-closed refusal does not name the forge it could not "
            "reach, so an operator cannot tell it from any other rc=2")
