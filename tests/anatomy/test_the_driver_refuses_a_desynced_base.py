"""The driver cuts a branch from the base every forge holds, or from nothing.

THE MEASUREMENT THIS PINS. 2026-08-19, twice in one session: `tools/loop-pr.py`
branched off the LOCAL `dev` while the forges' `dev` was five commits behind,
so the merge request carried a 598 KB diff instead of two lines. The reviewer
refused it on question 3 — a true positive, and a full CI cycle, a diagnosis, a
sync and a re-run to recover from. The reverse direction is quieter and worse:
a local base BEHIND the forges makes an MR whose three-dot diff still shows
only the patch, so the reviewer's byte-comparison PASSES — and the judged base
is not the base the merge lands on.

The invariant is therefore EQUALITY, both directions, verified before one byte
moves: `_base_alignment` refuses whenever any forge's tip of `base` differs
from the local commit the branch would be cut from, whenever a forge is
unreadable (fail closed — an unreadable forge is not an aligned one), and it
names `tools/forge-sync.py` in the refusal, because the fix is a sync and the
driver must never perform one itself.

CI-safe: `_base_alignment` is a pure function; the ordering check reads source.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DRIVER = REPO / "tools" / "loop-pr.py"

SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture(scope="module")
def drv():
    spec = importlib.util.spec_from_file_location("_loop_pr_align_gate", DRIVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_aligned_bases_pass(drv):
    ok, why = drv._base_alignment(
        SHA_A, {"gitea": (SHA_A, None), "gitlab": (SHA_A, None)}, "dev")
    assert ok, why
    assert why == ""


def test_a_forge_on_a_different_tip_refuses_and_names_the_sync(drv):
    """Either direction — ahead or behind — is the same refusal, because the
    function compares shas, not history. Direction diagnosis is forge-sync's
    job; the driver's job is only to not act on a base nobody agrees on."""
    ok, why = drv._base_alignment(
        SHA_A, {"gitea": (SHA_A, None), "gitlab": (SHA_B, None)}, "dev")
    assert not ok
    assert "gitlab" in why
    assert "forge-sync" in why, (
        "the refusal must name the tool that fixes it — a refusal without a "
        "remedy is what got the promotion hand-typed from memory")


def test_an_unreadable_forge_refuses(drv):
    """Fail closed: 'we could not ask' and 'it agrees' are the two readings
    this estate most often confuses (`_ci_hook_count`'s own docstring)."""
    ok, why = drv._base_alignment(
        SHA_A, {"gitea": (None, "gitea unreachable (URLError)"),
                "gitlab": (SHA_A, None)}, "dev")
    assert not ok
    assert "unreachable" in why or "cannot verify" in why


def test_an_absent_base_branch_refuses(drv):
    ok, why = drv._base_alignment(
        SHA_A, {"gitea": (None, None), "gitlab": (SHA_A, None)}, "dev")
    assert not ok
    assert "no branch" in why


def test_the_preflight_runs_before_the_branch_is_cut():
    """Source-order pin: `_base_alignment` is consulted in `land()` BEFORE the
    worktree is created. A preflight that runs after the commit exists is a
    post-mortem."""
    src = DRIVER.read_text(encoding="utf-8")
    land = src[src.index("def land("):src.index("def main(")]
    assert "_base_alignment(" in land, "land() no longer runs the topology preflight"
    assert land.index("_base_alignment(") < land.index('"worktree", "add"'), (
        "the alignment check must precede the worktree — a branch cut from a "
        "desynced base is already the 598 KB MR")
