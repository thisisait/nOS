"""The tofu Authentik path must refuse to run from a linked git worktree.

WHAT HAPPENED. Measured 2026-08-31: `--tags anatomy,authentik` run from a
worktree planned to CREATE the entire Authentik surface and then failed 40
times with `400 provider with this name already exists`.

The cause is structural, not a slip. The tofu state is gitignored, so it lives
only in the checkout that created it. A worktree therefore starts stateless —
and `tofu plan` does not read an empty state as "someone else owns this", it
reads it as "nothing exists yet". Every downstream rail then passed honestly: a
plan of N creates and zero destroys is exactly what a blank looks like, so the
destroy guard saw nothing to refuse, and the self-reconcile printed "no state
yet — nothing to reconcile" because it had nothing to reconcile against.

The estate survived only because Authentik's own uniqueness constraints
rejected each create. That is upstream's doing, not ours: a resource type
without such a constraint would have been silently duplicated.

WHY THIS IS THE RIGHT PLACE TO STOP IT. Not by teaching the guards to
distinguish a blank from a stateless worktree — a blank is run from the main
checkout by definition, so the distinction never needs making. A worktree has
no business owning the live SSO surface, and refusing before `tofu init` says
so once rather than in three places.
"""

from __future__ import annotations

import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks/tofu-authentik.yml"


def _tasks() -> list[dict]:
    """Every task in the file, flattened out of its block/rescue nesting."""
    def walk(items):
        for item in items or []:
            if not isinstance(item, dict):
                continue
            yield item
            for key in ("block", "rescue", "always"):
                yield from walk(item.get(key))
    return list(walk(yaml.safe_load(TASKS.read_text(encoding="utf-8"))))


def test_the_guard_exists_and_runs_before_init() -> None:
    names = [t.get("name", "") for t in _tasks()]
    guard = [i for i, n in enumerate(names) if "worktree" in n.lower()]
    assert guard, (
        "no worktree guard in tasks/tofu-authentik.yml — a converge from a "
        "worktree will plan to create the whole Authentik surface again")

    init = [i for i, n in enumerate(names) if "tofu init" in n]
    assert init, "tofu init task is gone — this gate's ordering claim is stale"
    assert min(guard) < min(init), (
        "the worktree guard runs AFTER `tofu init`. init in a stateless dir is "
        "what establishes the empty state the plan then acts on; the refusal "
        "has to come first")


def test_the_guard_actually_refuses() -> None:
    """It must FAIL, not warn. A warning in a converge log is not a stop."""
    for task in _tasks():
        # Both spellings: the file uses the FQCN, but `fail:` is equally valid
        # and a gate that only knows one is a gate that a rename defeats.
        action = task.get("ansible.builtin.fail") or task.get("fail")
        if "worktree" in task.get("name", "").lower() and action:
            msg = action.get("msg", "")
            assert "REFUS" in msg.upper(), (
                "the worktree task does not say it refused — an operator "
                f"reading the log cannot tell what happened: {msg[:120]}")
            assert task.get("when"), "the guard has no condition — it would refuse everywhere"
            return
    raise AssertionError(
        "the worktree task exists but does not use ansible.builtin.fail — "
        "anything softer lets the apply proceed")


def test_it_compares_git_dir_to_git_common_dir() -> None:
    """The detection must be git's own answer, not a path heuristic.

    A guess like "does the path contain 'worktrees'" passes on a worktree named
    anything else and fails on a main checkout that happens to sit in a
    directory of that name. `git rev-parse --git-dir --git-common-dir` returns
    two equal values in a main checkout and two different ones in a worktree,
    which is the fact itself rather than a proxy for it.
    """
    body = TASKS.read_text(encoding="utf-8")
    assert "--git-dir --git-common-dir" in body, (
        "the guard no longer asks git whether this is a worktree")
    assert "stdout_lines[0] != " in body.replace("  ", " ") or \
           "stdout_lines[0] !=" in body, (
        "the guard no longer compares the two git dirs")
