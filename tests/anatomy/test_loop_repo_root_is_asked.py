"""Where the repo is, is a question for the environment — not for `__file__`.

MEASURED IN THE LIVE DAEMON, 2026-08-03. Every judge run inside Bone died on:

    unknown gate set: judge registry not found: /state/judge-sets.yml

`judges._default_repo_root()` was `Path(__file__).resolve().parents[3]`, true of
`<repo>/files/anatomy/bone/judges.py` and false of where Bone actually runs:
the role DEPLOYS the module to a flat `~/bone/`, where four parents up is `/`.

The reader half of the same engine was never affected — `weaknesses.repo_root()`
asked `PLAYBOOK_DIR`, which the launchd plist sets to the checkout. So the loop
could always SEE its weaknesses and could never JUDGE anything, and the split
was invisible because the two halves were exercised separately.

WHY THE EXISTING SUITE COULD NOT CATCH IT — the part worth remembering:

    `judges.load_registry(repo_root)` takes the root as a PARAMETER, and every
    harness passes it explicitly. The default is therefore reached ONLY in
    production. `test_loop_determinism_across_harnesses.py` — the gate whose
    entire subject is "the loop must mean the same thing under every harness" —
    supplies its own `repo_root` on line 126 and so proved determinism across
    harnesses that all agreed because none of them asked.

    A default that no test reaches is not covered by the tests that use the
    thing it defaults for.

This file therefore tests the RESOLVER, with the environment manipulated, and
never a run that brings its own answer. It is the four-trees rule
(`docs/doctrine/four-trees.md` R2) expressed as code: Bone reads tree 2, and a
module that infers its location from its own file believes it is in tree 2 when
it is in tree 4.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"


@pytest.fixture()
def judges_mod():
    """Import `judges` the way Bone does — flat, with the bone dir on the path."""
    sys.path.insert(0, str(BONE))
    try:
        mod = importlib.import_module("judges")
        yield mod
    finally:
        sys.path.remove(str(BONE))


def test_the_resolver_does_not_infer_from_its_own_location(judges_mod, monkeypatch, tmp_path):
    """The defect, stated as the thing that must stay false.

    With the environment pointing somewhere real, the resolver must return that
    — not a path derived from where `judges.py` happens to be sitting. Under
    the old implementation this returned the repo root regardless of the
    environment, which is exactly why it looked correct in the checkout.
    """
    monkeypatch.setenv("NOS_LOOP_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("PLAYBOOK_DIR", raising=False)
    assert judges_mod._default_repo_root() == tmp_path, (
        "the repo root is being inferred rather than asked. In the deployed "
        "daemon that resolves to `/` and every gate set becomes unfindable."
    )


def test_playbook_dir_is_honoured_because_that_is_what_the_plist_sets(
    judges_mod, monkeypatch, tmp_path
):
    """The variable that actually carries the answer in production."""
    monkeypatch.delenv("NOS_LOOP_REPO_ROOT", raising=False)
    monkeypatch.setenv("PLAYBOOK_DIR", str(tmp_path))
    assert judges_mod._default_repo_root() == tmp_path, (
        "PLAYBOOK_DIR is ignored. It is Bone's existing convention and the "
        "launchd plist sets it; ignoring it is what left the judges homeless."
    )


def test_the_reader_and_the_judges_give_the_same_answer(monkeypatch, tmp_path):
    """One fact, one spelling.

    They disagreed, and the disagreement was silent because each half is used
    on its own. Delegation rather than a second correct-looking copy is the
    point — a copy would pass this test the day it was written and drift after.
    """
    sys.path.insert(0, str(BONE))
    try:
        judges = importlib.import_module("judges")
        weaknesses = importlib.import_module("weaknesses")
        monkeypatch.setenv("NOS_LOOP_REPO_ROOT", str(tmp_path))
        assert weaknesses.repo_root() == judges._default_repo_root() == tmp_path
        src = (BONE / "weaknesses.py").read_text(encoding="utf-8")
        assert "judges._default_repo_root()" in src, (
            "weaknesses.repo_root re-implements the resolution instead of "
            "delegating. Two copies agreeing today is how this started."
        )
    finally:
        sys.path.remove(str(BONE))


def test_the_callers_directory_is_never_the_answer(judges_mod, monkeypatch, tmp_path):
    """The mistake the FIRST repair made, pinned so it is not made twice.

    Fixing the deployed-daemon bug by falling back to `os.getcwd()` looked
    obviously right and broke `test_both_harnesses_resolve_the_same_registry_
    from_the_source_not_the_cwd` immediately — that gate exists because
    resolving the registry against the caller's directory would mean a gate set
    says one thing in CI and another at 03:00, which is the one property the
    registry is in the repo to guarantee.

    Falling back to the SOURCE location is fine, but only when validated: it is
    right in a checkout and meaningless once deployed. Unvalidated, it silently
    returned `/`, which is how this started.
    """
    monkeypatch.delenv("NOS_LOOP_REPO_ROOT", raising=False)
    monkeypatch.delenv("PLAYBOOK_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert judges_mod._default_repo_root() != tmp_path, (
        "the resolver fell back to the caller's cwd. Two harnesses in two "
        "directories would then read two registries and both call the result "
        "a verdict."
    )
    # Read the CODE, not the prose. A substring check failed here first, on the
    # docstring that explains why getcwd is forbidden — a gate tripping over
    # its own explanation, the same shape as a comment about a Jinja trap that
    # was itself written in the trap. The AST sees calls; it does not see
    # sentences about calls.
    import ast

    tree = ast.parse((BONE / "judges.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_default_repo_root"
    )
    calls = {
        ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)
    }
    assert "os.getcwd" not in calls, (
        "os.getcwd() is CALLED in the resolver — see this test's docstring. "
        f"(calls found: {sorted(calls)})"
    )


def test_the_registry_path_is_relative_to_that_root(judges_mod):
    """A guard on the symptom, so the failure is legible if it returns."""
    assert not judges_mod.REGISTRY_RELPATH.startswith("/"), (
        "REGISTRY_RELPATH became absolute — it is joined onto the repo root, "
        "and a leading slash would discard the root entirely"
    )
