"""Anatomy gate — gate set `repo` must be able to judge the loop's own tests.

THE MEASURED DEFECT (2026-08-20, proposal 5ea07907 and every `repo` verdict
before it): `run_gate_set("repo")` ALWAYS failed with 17-18 red tests, every
one of them a loop-engine gate — while the same suite, in the same kind of
sandbox, passed when invoked by hand. Three causes, each pinned below:

  1. THE RECURSIVE MUTEX (16 failures). The registry declared
     `exclusive_resource: nos_entity` on genome-codegen and pytest-anatomy, so
     the outer `repo` run held `$TMPDIR/nos-loop-nos_entity.lock` around the
     entire pytest-anatomy judge. Sixteen gates INSIDE that pytest call
     `run_gate_set` on sets containing genome-codegen; each found the lock
     held, skipped the judge, and went INDETERMINATE — failing their own
     assertions. The lock guarded nothing: DECISION 2d gives every set its own
     worktree, so the `nos_entity.py` two runs touch are two files, and the
     judge argv is `--check`, which writes nothing.

  2. TWO NAMES FOR ONE TREE (1 failure). `git_worktree_sandbox` returned the
     raw `mkdtemp` path (`/var/folders/...` on macOS); `run_gate_set` exported
     it as NOS_LOOP_REPO_ROOT/PLAYBOOK_DIR; code inside the sandbox that
     resolves its own location got `/private/var/...`. The determinism gate
     compared the two and failed — only ever under the engine.

  3. QUOTED SUMMARIES SUMMED (a work-count lie, found while measuring 1+2).
     `_pytest_counts` summed EVERY summary-shaped string in the output. The
     judged suite quotes inner pytest summaries in its failure output and even
     in parametrized test IDs ("250 skipped"), so the judge recorded
     work=15450 against a true 3855 — and an inner "16 failed" line could
     have failed an outer run whose own summary was green.

Why the recursion is non-negotiable: pytest-anatomy judging a tree that
contains pytest-anatomy's own gates is the loop judging its own engine, which
is the only arrangement in which a proposal against the engine is judgeable at
all. Excluding the engine's gates from the judged suite would leave the
engine's own oracle unrun — the calm-by-absence shape this suite refuses.

CI-safe: one `git worktree add` of this repo, no network, no daemon.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
JUDGES_PY = REPO / "files" / "anatomy" / "bone" / "judges.py"
REGISTRY_YML = REPO / "state" / "judge-sets.yml"


def _load_judges():
    spec = importlib.util.spec_from_file_location("nos_loop_judges_own_gates", JUDGES_PY)
    assert spec and spec.loader, f"cannot load {JUDGES_PY}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["nos_loop_judges_own_gates"] = module
    spec.loader.exec_module(module)
    return module


J = _load_judges()


def test_no_committed_judge_takes_a_machine_wide_mutex():
    """The registry declares no exclusive_resource — consciously.

    A machine-global lock held around pytest-anatomy starves every engine gate
    running inside it (cause 1 above). Re-adding one is not forbidden forever:
    whoever loosens this gate must ALSO prove the loop-engine gates hermetic
    against a held lock (their `run_gate_set` calls must pass an isolated
    `lock_dir`), or gate set `repo` goes permanently red again. The `_FileLock`
    mechanism itself stays pinned by
    `test_a_held_exclusive_resource_is_indeterminate_not_a_pass` and
    `test_both_harnesses_name_the_same_exclusive_lock`.
    """
    doc = yaml.safe_load(REGISTRY_YML.read_text(encoding="utf-8"))
    offenders = {
        name: spec["exclusive_resource"]
        for name, spec in doc.get("judges", {}).items()
        if spec.get("exclusive_resource")
    }
    assert not offenders, (
        f"judges declare a machine-wide mutex again: {offenders} — the outer "
        f"judge will hold it around pytest-anatomy and starve the engine's own "
        f"gates (see this file's docstring before loosening)"
    )


def test_the_sandbox_names_its_tree_canonically():
    """`git_worktree_sandbox` returns a path that IS its own resolution.

    On macOS `mkdtemp` answers under `/var/folders/...`, a symlink into
    `/private/var/...`; an unresolved path exported as the repo root gives the
    judged tree two names, and one gate inside the sandbox compares them
    (cause 2 above).
    """
    path, sha, cleanup = J.git_worktree_sandbox(REPO)
    try:
        assert path == path.resolve(), (
            f"sandbox path {path} is not canonical (resolves to {path.resolve()})"
        )
        assert sha and len(sha) == 40
    finally:
        cleanup()


def test_the_pytest_work_count_reads_one_summary_not_every_quotation():
    """`_pytest_counts` parses the LAST summary line; a run prints exactly one.

    The judged suite quotes inner pytest summaries in failure output and in
    parametrized test IDs (cause 3 above). Summing them inflated the work
    ratchet 4x and let a quoted "failed" fail a green run.
    """
    output = (
        "collected 3855 items\n"
        "FAILED tests/x.py::test_all_skipped[250 skipped in 4.10s\\n]\n"
        "E   AssertionError: inner run said: 16 failed, 52 passed in 29.66s\n"
        "3855 passed, 59 skipped in 268.47s\n"
    )
    counts = J._pytest_counts(output)
    assert counts == {"passed": 3855, "skipped": 59}, counts
    # And nothing summary-shaped at all is still an honest "could not tell".
    assert J._pytest_counts("no summary here") is None
