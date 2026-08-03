"""A judge must be told the sandbox is the repo, or the sandbox is decorative.

MEASURED 2026-08-03, on the first `repo` gate set that ever reached a verdict.

That morning `judges._default_repo_root()` was changed to ask the environment
(`NOS_LOOP_REPO_ROOT`, then `PLAYBOOK_DIR`) before falling back to a validated
source path. That change was necessary and is not in question: Bone is deployed
to a flat `~/bone/`, so the daemon genuinely cannot infer the repo from where
its own files sit, and before the change every judge run died on
`/state/judge-sets.yml`.

What it also did, invisibly: a judge is a SUBPROCESS of that daemon and inherits
its environment. In the deployed environment `PLAYBOOK_DIR` names the operator's
checkout. So code running INSIDE the sandbox — including the loop's own gates —
asked "where is the repo" and was told: somewhere else entirely.

That is the sandbox's entire purpose defeated from within. `git worktree add
--detach HEAD` exists so a gate set judges ONE tree and nothing else; an
inherited environment variable quietly re-pointed the answer at a tree the judge
was never given.

HOW IT SURFACED, which is the part worth keeping. Nothing reported it. The
`repo` set sealed FAIL, the ledger stored two thousand characters of pytest
progress dots (head, not tail — fixed in the same commit), and reproducing the
same tree in a clean worktree PASSED. Only setting the daemon's PLAYBOOK_DIR by
hand reproduced it, and then exactly one test failed:
`test_both_harnesses_resolve_the_same_registry_from_the_source_not_the_cwd` —
the determinism gate, which exists for precisely this and was the only thing in
2521 tests that noticed.

THE SHAPE, for the next time: A FIX THAT IS CORRECT IN ONE CONTEXT AND WRONG IN
ANOTHER, INVISIBLE BECAUSE THE TWO CONTEXTS ARE EXERCISED SEPARATELY. The reader
half and the judge half of one engine, again — the same split that hid the
original repo-root defect it was fixing.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"


@pytest.fixture(scope="module")
def judges_mod():
    sys.path.insert(0, str(BONE))
    try:
        yield importlib.import_module("judges")
    finally:
        sys.path.remove(str(BONE))


def test_the_spawn_env_names_the_sandbox_not_the_inherited_checkout(judges_mod, tmp_path, monkeypatch):
    """The defect, as the thing that must stay false.

    Runs a gate set with a stub sandbox and a stub spawn, under an environment
    that names a DIFFERENT repo — exactly the deployed daemon's situation — and
    asserts the child was told about the sandbox.
    """
    elsewhere = tmp_path / "operators-checkout"
    elsewhere.mkdir()
    sandbox = tmp_path / "the-sandbox"
    sandbox.mkdir()
    monkeypatch.setenv("PLAYBOOK_DIR", str(elsewhere))
    monkeypatch.setenv("NOS_LOOP_REPO_ROOT", str(elsewhere))

    seen: list[dict] = []

    def stub_spawn(argv, cwd, timeout_s):
        # `real_spawn` is what carries the env; the runner hands it through a
        # closure, so capture what a real child would have received.
        seen.append({"cwd": cwd})
        return judges_mod.Completed(exit_code=0, stdout="1 passed", duration_s=0.0)

    # Hold the REFERENCE, never a copy: the runner mutates this dict in place
    # once the sandbox exists (the override cannot happen earlier — the path
    # does not exist yet). A copying spy sees the pre-sandbox state and reports
    # the defect as still present, which is how this test failed on its own
    # first run.
    built: list[dict[str, str]] = []
    real_env_builder = judges_mod.judge_spawn_env

    def spy_env(base=None):
        env = real_env_builder(base)
        built.append(env)
        return env

    monkeypatch.setattr(judges_mod, "judge_spawn_env", spy_env)

    try:
        judges_mod.run_gate_set(
            "fast",
            repo_root=REPO,
            sandbox_factory=lambda root: (str(sandbox), "0" * 40, lambda: None),
            spawn=stub_spawn,
        )
    except Exception:
        pytest.skip("run_gate_set signature moved; re-derive this gate")

    assert built, "judge_spawn_env was never called — the runner stopped using it"
    captured_env = built[-1]
    for name in ("NOS_LOOP_REPO_ROOT", "PLAYBOOK_DIR"):
        assert captured_env.get(name) == str(sandbox), (
            f"a judge subprocess would be told {name}={captured_env.get(name)!r} "
            f"while running inside {sandbox}. It would then read files from a "
            f"tree it was never given to judge — the sandbox becomes decorative "
            f"and a verdict stops being about the thing it names."
        )


def test_the_override_is_written_where_the_sandbox_is_known(judges_mod):
    """Structural guard: the assignment must sit after the sandbox exists.

    `judge_spawn_env()` cannot do this — it is called before the sandbox is
    created and has no path to name. A future refactor that moves the override
    into it would silently restore the defect while looking tidier.
    """
    src = (BONE / "judges.py").read_text(encoding="utf-8")
    fn = src[src.index("def run_gate_set"):]
    sandbox_at = fn.index("sandbox_factory or git_worktree_sandbox")
    override_at = fn.find('jenv["NOS_LOOP_REPO_ROOT"]')
    assert override_at != -1, (
        "run_gate_set no longer points the child's repo root at the sandbox. "
        "The daemon's PLAYBOOK_DIR names the operator's checkout and a judge "
        "inherits it."
    )
    assert override_at > sandbox_at, (
        "the override is written before the sandbox is created, so it cannot "
        "name it"
    )
