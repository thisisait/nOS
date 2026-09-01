"""Anatomy CI gate — the nightly tofu drift plan must skip a worktree, not cry drift.

MEASURED 2026-09-01. The Pulse catalog stores an absolute `{{ playbook_dir }}`
command, so a converge run from a git worktree re-registered
`authentik-tofu-drift:tofu-drift-plan` to point there. A worktree carries the
rendered tfvars and NOT the state, so `tofu plan` reported

    Plan: 101 to add, 0 to change, 0 to destroy.

against a main checkout holding 109 real resources — phantom drift, filed at
medium, every night.

WHAT THE GUARD MUST NOT DO, because the first version did it: compare
`--git-dir` against `--git-common-dir`. From a SUBDIRECTORY git answers the
first absolutely and the second relatively (`/…/nOS/.git` vs `../../.git`), so
a string compare calls the main checkout a worktree too and disables the job
everywhere. (`tasks/tofu-authentik.yml` uses that pair correctly because it runs
from the repo ROOT, where both are `.git`.)

A linked worktree's ABSOLUTE git-dir is always `<common>/worktrees/<name>`.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = (REPO / "files/anatomy/plugins/authentik-tofu-drift-base"
          / "skills/run-tofu-drift.sh")


def _body() -> str:
    """Source with comments stripped — a comment naming the check is not one."""
    return "\n".join(ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_job_detects_a_worktree_at_all():
    body = _body()
    assert "worktrees/" in body, (
        f"{SCRIPT.name} no longer detects a linked worktree. The Pulse catalog "
        "stores an absolute playbook_dir, so one converge from a worktree "
        "re-points this job at a checkout with tfvars and no state — and every "
        "resource then reads as missing")
    assert "--absolute-git-dir" in body, (
        "the detection must use --absolute-git-dir; see the docstring for what "
        "the --git-dir/--git-common-dir pair does from a subdirectory")


def test_it_does_not_compare_two_spellings_of_one_path():
    """The regression that disabled the job everywhere. `--git-common-dir` is
    answered RELATIVE from a subdirectory, so comparing it to the absolute
    `--git-dir` is comparing representations, not directories."""
    body = _body()
    assert "--git-common-dir" not in body, (
        f"{SCRIPT.name} is back to comparing --git-dir with --git-common-dir. "
        "Run from $TOFU_DIR (a subdirectory) those differ as STRINGS in the "
        "main checkout too, so the guard skips everywhere and the drift job "
        "silently stops running")


def test_the_worktree_skip_is_clean_not_a_failure():
    """Exit 0. A worktree is not an error condition and must not spend the
    job's error-notify path — the contract reserves 1 for drift and 2 for a
    plan error."""
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"worktrees/\*\)(.*?)\besac", src, re.S)
    assert m, "the worktree branch is no longer a case arm; re-read this gate"
    assert "exit 0" in m.group(1), (
        "the worktree branch does not exit 0. Skipping a checkout that cannot "
        "hold the state is a clean skip, not drift and not a plan error")


def test_the_findings_code_is_declared_so_drift_is_not_read_as_failure():
    """rc=1 is DRIFT FOUND — the script's own header says so. Undeclared, the
    notifier filed `Pulse job … failing (rc=1)` at HIGH for a detector doing
    exactly its job (hidden fee 34, the next consumer it warned about)."""
    manifest = (REPO / "files/anatomy/plugins/authentik-tofu-drift-base"
                / "plugin.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s*findings_exit_codes:\s*\[\s*1\s*\]", manifest, re.M), (
        "the drift job does not declare findings_exit_codes: [1]. gitleaks, "
        "discovery and loop all declare theirs; without it every detected "
        "drift is reported as a failing job")
