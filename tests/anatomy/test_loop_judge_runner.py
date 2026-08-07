"""Anatomy gate — the judge runner may not report a false green.

Contract: ``docs/idea/11-agentic-loop-contract.md`` §2. This pins the PROPERTIES
of ``files/anatomy/bone/judges.py``:

  1. a FAILING judge produces a FAILING verdict;
  2. an ABSENT judge produces a NON-PASSING verdict — in every flavour of
     absence measured in the contract's §0, not just the convenient one;
  3. two runs of the same gate set against the same tree agree.

WHY THIS FILE EXISTS AT ALL, stated plainly: three of the five judges in
``state/judge-sets.yml`` return exit 0 when they did no work. That is the same
defect as ``docs/hidden_fees/08-empty-stack-reads-as-success.md`` — sitting
inside the judges the loop depends on. The runner is the layer that has to
refuse to launder those zeros into a PASS, so the absence cases below are the
spine of this file and not its edge cases.

WHAT THIS FILE CAN AND CANNOT DO, so nobody mistakes it for proof the loop
works:

  CAN: prove the runner's decision logic — that absence, crashes, unparseable
  reports, held locks, missing sandboxes and shrunken scope all resolve to
  INDETERMINATE; that a FAIL survives; that the verdict is reproducible; that
  no caller can inject a result. It does this with a spawn double that replaces
  THE PROCESS (an exit code and some bytes), never THE JUDGMENT — the adapters
  under test still compute every verdict. One test runs a REAL judge twice.

  CANNOT: prove the five judges are correct oracles, or that a green `fast` set
  means the tree is good. A judge that is wrong-but-consistent is invisible here
  and the contract says so (§9.9). Runtime truth stays with the judges
  themselves.

CI-safe: no network, no daemon, no Docker. The one real subprocess is
``tools/genome-codegen.py --check``, which is pure repo I/O.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
JUDGES_PY = REPO / "files" / "anatomy" / "bone" / "judges.py"
REGISTRY_YML = REPO / "state" / "judge-sets.yml"


def _load_judges():
    """Import judges.py by path — Bone's modules are flat, not a package."""
    spec = importlib.util.spec_from_file_location("nos_loop_judges", JUDGES_PY)
    assert spec and spec.loader, f"cannot load {JUDGES_PY}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["nos_loop_judges"] = module
    spec.loader.exec_module(module)
    return module


J = _load_judges()


# ── helpers ────────────────────────────────────────────────────────────────


def _registry():
    return J.load_registry(REPO)


def _spec(name: str):
    return _registry().judges[name]


def _one_judge_registry(name: str, gate_set: str = "solo"):
    """A registry holding ONE real judge spec, so a test can run it alone."""
    reg = _registry()
    return J.Registry(
        judges={name: reg.judges[name]},
        gate_sets={gate_set: J.GateSetSpec(name=gate_set, judges=(name,))},
    )


def _fake_spawn(**by_judge):
    """A spawn double. It replaces THE PROCESS, not THE JUDGMENT.

    It returns exactly what a real subprocess returns — an exit code and some
    bytes. It cannot return a Result; the adapters compute that. Mapping is by
    the script/executable name found in argv.
    """

    def spawn(argv, cwd, timeout_s):
        key = _argv_key(argv)
        if key not in by_judge:
            raise AssertionError(f"unexpected judge spawned: {argv}")
        return by_judge[key]

    return spawn


def _argv_key(argv) -> str:
    """Map an argv to the judge's short name.

    ``-m pytest`` is handled explicitly. An earlier draft did not, so
    ``["python3","-m","pytest",...]`` keyed as "python3", missed the double's
    table, and the double raised — which the runner correctly turned into a
    CRASHED/INDETERMINATE run. Two pytest tests then passed while asserting
    "not PASS" without ever exercising the adapter they were written for. The
    retro-verification harness is what surfaced it: their defect was
    reintroduced and they stayed green.
    """
    argv = list(argv)
    if "-m" in argv:
        i = argv.index("-m")
        if i + 1 < len(argv):
            return argv[i + 1]
    for arg in argv:
        if arg.endswith(".py"):
            return pathlib.Path(arg).stem
    return pathlib.Path(argv[0]).name


# Realistic process outputs, copied from MEASURED runs (contract §0 + the
# build-time re-measurement). Using the real text matters: a parser tuned to
# invented output is a parser nobody has tested.
GREEN_ANSIBLE_LINT = J.Completed(
    exit_code=0,
    stdout="",
    # NOTE: this line really is on STDERR. A stdout-only parser reads no work
    # count and turns every green ansible-lint run INDETERMINATE.
    stderr=(
        "Passed: 0 failure(s), 0 warning(s) in 1475 files processed "
        "of 3147 encountered. Last profile that met the validation criteria "
        "was 'production'."
    ),
)
GREEN_GENOME = J.Completed(exit_code=0, stdout="genome artifacts current (2 checked)\n")
STALE_GENOME = J.Completed(
    exit_code=1,
    stdout="STALE generated artifacts: files/anatomy/module_utils/nos_entity.py\n",
)


def _green_fast():
    return _fake_spawn(**{"ansible-lint": GREEN_ANSIBLE_LINT, "genome-codegen": GREEN_GENOME})


def _always_true(_requirement: str) -> bool:
    return True


# ── 0. Guard the guard ─────────────────────────────────────────────────────


def test_the_registry_actually_loads_and_is_not_empty():
    """A registry that silently yields nothing passes every case below."""
    reg = _registry()
    assert len(reg.judges) >= 5, f"only {len(reg.judges)} judges — registry drift?"
    assert {"fast", "repo", "live", "full"} <= set(reg.gate_sets)


def test_a_green_fast_set_really_does_pass():
    """The counterweight to every fail-closed test here.

    Without this, a runner hard-wired to return INDETERMINATE would satisfy the
    entire rest of the file. A gate that can only ever go red is not measuring
    anything.
    """
    verdict = J.run_gate_set(
        "fast", registry=_registry(), repo_root=REPO, spawn=_green_fast(), probe=_always_true
    )
    assert verdict.result is J.Result.PASS, verdict.reason
    assert verdict.passed is True
    assert not verdict.blocks_acceptance
    assert [r.work for r in verdict.runs] == [1475, 2]


# ── 1. A FAILING judge produces a FAILING verdict ──────────────────────────


def test_a_failing_judge_fails_the_set():
    verdict = J.run_gate_set(
        "fast",
        registry=_registry(),
        repo_root=REPO,
        spawn=_fake_spawn(**{"ansible-lint": GREEN_ANSIBLE_LINT, "genome-codegen": STALE_GENOME}),
        probe=_always_true,
    )
    assert verdict.result is J.Result.FAIL
    assert verdict.blocks_acceptance
    assert "genome-codegen" in verdict.reason


def test_ansible_lint_fails_on_exit_two_not_one():
    """MEASURED: ansible-lint's failure code is 2.

    A naive ``!= 0`` check is right by accident; a naive ``== 1`` check is
    wrong. Exit 2 must be a clean FAIL — not INDETERMINATE, which would let a
    genuinely red lint be reported as "we don't know" and stop blocking.
    """
    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("ansible-lint", "fast"),
        repo_root=REPO,
        spawn=_fake_spawn(**{"ansible-lint": J.Completed(exit_code=2, stderr="Failed: 3 failure(s)")}),
        probe=_always_true,
    )
    assert verdict.result is J.Result.FAIL


def test_one_fail_beats_any_number_of_passes():
    """DECISION 2a — no majority, no weighting, no "mostly green"."""
    verdict = J.run_gate_set(
        "fast",
        registry=_registry(),
        repo_root=REPO,
        spawn=_fake_spawn(**{"ansible-lint": GREEN_ANSIBLE_LINT, "genome-codegen": STALE_GENOME}),
        probe=_always_true,
    )
    assert verdict.result is J.Result.FAIL


def test_a_fail_outranks_an_indeterminate():
    """A red judge must not be masked by a broken one — and vice versa.

    If INDETERMINATE won, a proposer could silence a real FAIL by breaking any
    other judge in the set.
    """
    verdict = J.run_gate_set(
        "fast",
        registry=_registry(),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{
                "ansible-lint": J.Completed(exit_code=99, stderr="who knows"),
                "genome-codegen": STALE_GENOME,
            }
        ),
        probe=_always_true,
    )
    assert verdict.result is J.Result.FAIL


# ── 2. An ABSENT judge produces a NON-PASSING verdict ──────────────────────
#
# Every case below is a measured shape from the contract's §0. Each asserts
# `is not PASS` first (the property that matters) and then the specific value.


def test_absent_requirement_is_indeterminate_and_the_judge_never_runs():
    """DECISION 2c — a judge whose requires: are absent never runs degraded."""
    spawned: list = []

    def spy(argv, cwd, timeout_s):
        spawned.append(argv)
        return J.Completed(exit_code=0)

    verdict = J.run_gate_set(
        "live",
        registry=_registry(),
        repo_root=REPO,
        spawn=spy,
        probe=lambda _r: False,  # nothing is available
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert verdict.blocks_acceptance
    assert spawned == [], "a judge with absent requirements was executed anyway"
    assert all(r.status == "skipped" for r in verdict.runs)


def test_nos_smoke_zero_entries_is_not_a_pass():
    """M2, re-confirmed at build time:

        $ python3 tools/nos-smoke.py --include zzz-nonexistent-service --no-jsonl
        smoke catalog yielded zero entries (check filters / install_* flags)
        EXIT=0

    Exit 0 with no probes run is the headline false green this engine exists to
    refuse. It must never be a PASS.
    """
    verdict = J.run_gate_set(
        "live",
        registry=_one_judge_registry("nos-smoke", "live"),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{
                "nos-smoke": J.Completed(
                    exit_code=0,
                    stderr="smoke catalog yielded zero entries (check filters / install_* flags)\n",
                )
            }
        ),
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert "could not be read" in verdict.reason or "min_work" in verdict.reason


@pytest.mark.parametrize("summary", ["2 skipped in 0.22s\n", "250 skipped in 4.10s\n"])
def test_pytest_all_skipped_is_not_a_pass(summary):
    """M3, re-confirmed at build time:

        $ env -u WING_API_TOKEN HOME=/tmp/emptyhome python3 -m pytest \
              tests/anatomy/test_hub_url_audit.py -q -rs
        2 skipped in 0.22s
        EXIT=0

    Skipped is not executed. A suite that ran nothing proves nothing.

    THE 250-SKIPPED CASE IS THE LOAD-BEARING ONE, and the small one alone was
    not enough. At "2 skipped" the min_work ratchet refuses the run whether or
    not skipped counts as work, so a runner that wrongly counted skips would
    still look correct. 250 is what the whole anatomy suite skipping out
    actually looks like — above min_work — so only the "skipped is not
    executed" rule itself can refuse it. Retro-verification caught this: the
    defect was reintroduced and the single-case test stayed green.
    """
    verdict = J.run_gate_set(
        "repo",
        registry=_one_judge_registry("pytest-anatomy", "repo"),
        repo_root=REPO,
        spawn=_fake_spawn(**{"pytest": J.Completed(exit_code=0, stdout=summary)}),
        probe=_always_true,
        sandbox_factory=lambda root: (root, "sha-fake", lambda: None),
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert verdict.runs[0].work == 0, "skipped tests were counted as executed work"


#: MEASURED on this tree: `python3 -m pytest tests/anatomy -q`, SIGINT to the
#: child 20 s in. pytest prints its interrupt banner and THEN a well-formed,
#: entirely pass-shaped summary, and exits 2.
INTERRUPTED_PYTEST = J.Completed(
    exit_code=2,
    stdout=(
        "\n!!!!!!!!!!!!!!!!!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "/opt/homebrew/lib/python3.13/site-packages/_pytest/runner.py:341: "
        "KeyboardInterrupt\n(to show a full traceback on KeyboardInterrupt use "
        "--full-trace)\n454 passed in 19.94s\n"
    ),
)


def test_an_interrupted_pytest_is_not_a_pass():
    """A judge killed 20% of the way through read PASS.

    `_adapt_pytest_summary` never looked at `done.exit_code`; it parsed the
    summary line, saw no failures, and returned PASS. 454 of 2432 tests, exit 2,
    reported green — and the work ratchet could not catch it either, because 454
    was above the old min_work of 200. The signal decided the verdict: SIGTERM
    (no summary) was INDETERMINATE while SIGINT (a partial summary) was a pass.

    Reachable without any parent involvement: a supervisor signalling the child
    pid alone, `pytest.exit()`, or a plugin/fixture raising KeyboardInterrupt.
    """
    verdict = J.run_gate_set(
        "repo",
        registry=_one_judge_registry("pytest-anatomy", "repo"),
        repo_root=REPO,
        spawn=_fake_spawn(**{"pytest": INTERRUPTED_PYTEST}),
        probe=_always_true,
        sandbox_factory=lambda root: (root, "sha-fake", lambda: None),
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert "exited 2" in verdict.reason, verdict.reason

    # The adapter is where it must hold — via the registry's real spec, so this
    # is not a claim about a hand-built one.
    result, reason = J.ADAPTERS["pytest_summary"](_spec("pytest-anatomy"), INTERRUPTED_PYTEST)
    assert result is J.Result.INDETERMINATE, reason


def test_a_completed_pytest_run_still_passes():
    """The counterweight: exit 0 with a real summary is a real PASS. Without
    this, an adapter hard-wired to INDETERMINATE would satisfy the test above."""
    verdict = J.run_gate_set(
        "repo",
        registry=_one_judge_registry("pytest-anatomy", "repo"),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{"pytest": J.Completed(exit_code=0, stdout="3050 passed, 27 skipped in 252.00s\n")}
        ),
        probe=_always_true,
        sandbox_factory=lambda root: (root, "sha-fake", lambda: None),
    )
    assert verdict.result is J.Result.PASS, verdict.reason
    assert verdict.runs[0].work == 3050


def test_an_interrupted_pytest_that_did_fail_is_still_a_fail():
    """Ordering, and it is deliberate (DECISION 2b): a red is a red. Downgrading
    a real failure to INDETERMINATE because the run was cut short would hide
    it, and INDETERMINATE means "we do not know", not "we know it is broken"."""
    result, _ = J.ADAPTERS["pytest_summary"](
        _spec("pytest-anatomy"),
        J.Completed(exit_code=2, stdout="KeyboardInterrupt\n3 failed, 451 passed in 20s\n"),
    )
    assert result is J.Result.FAIL


def test_work_below_the_ratchet_is_not_a_pass():
    """min_work is a BLAST_RADIUS_CEILING-style ratchet.

    ansible-lint processes 1475 of 3147 encountered files and nothing else pins
    that ratio, so silent scope loss would read as green. A run that suddenly
    processes 12 files is not a smaller success, it is an unexplained one.
    """
    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("ansible-lint", "fast"),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{
                "ansible-lint": J.Completed(
                    exit_code=0,
                    stderr="Passed: 0 failure(s), 0 warning(s) in 12 files processed of 2979 encountered.",
                )
            }
        ),
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert "min_work" in verdict.reason


def test_corpus_diff_exit_zero_while_disagreeing_is_a_fail_not_a_pass():
    """MEASURED: under --no-ledger the script returns `3 if removalShaped else 0`.

    So a DISAGREE report exits 0. The exit code is not the verdict; ``.agrees``
    is. Reading the exit code here would invert the result.
    """
    verdict = J.run_gate_set(
        "live",
        registry=_one_judge_registry("cortex-corpus-diff", "live"),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{
                "cortex-corpus-diff": J.Completed(
                    exit_code=0,
                    stdout='{"agrees": false, "tables": [{"name": "knowledge_objects"}]}',
                )
            }
        ),
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.FAIL


def test_corpus_diff_void_night_is_indeterminate_not_a_pass():
    """The organ-unreachable path prints NO json and still exits 0.

    Note the asymmetry it corrects: in the script itself an unreachable
    incumbent is red (exit 2) but an unreachable organ is green (`night VOID`
    → 0). An unparseable report is "we do not know", which is what that
    situation actually is.
    """
    verdict = J.run_gate_set(
        "live",
        registry=_one_judge_registry("cortex-corpus-diff", "live"),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{
                "cortex-corpus-diff": J.Completed(
                    exit_code=0,
                    stdout="",
                    stderr="cortex-corpus-diff: cortex unreachable — night VOID: timeout",
                )
            }
        ),
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE


def test_an_unknown_exit_code_is_indeterminate_not_a_pass():
    """Outside pass_exit and fail_exit is unknown, and unknown is not success."""
    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("ansible-lint", "fast"),
        repo_root=REPO,
        spawn=_fake_spawn(**{"ansible-lint": J.Completed(exit_code=137, stderr="Killed")}),
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE


def test_a_killed_judge_is_indeterminate_not_a_pass():
    """CONSTRAINT B — a process that never delivered an exit status.

    Being killed is an unattended loop's NORMAL failure mode, which is exactly
    why it may not resolve to the value that lets a proposal through.
    """
    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("genome-codegen", "fast"),
        repo_root=REPO,
        spawn=_fake_spawn(
            **{"genome-codegen": J.Completed(exit_code=None, stdout="", timed_out=True)}
        ),
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert verdict.runs[0].status == "crashed"


def test_a_spawn_that_raises_is_indeterminate_not_a_pass():
    def exploding(argv, cwd, timeout_s):
        raise OSError("no fork for you")

    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("genome-codegen", "fast"),
        repo_root=REPO,
        spawn=exploding,
        probe=_always_true,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.runs[0].status == "crashed"


def test_a_missing_executable_is_indeterminate_not_a_pass():
    """The judge binary being absent is a requirement being absent."""
    reg = _registry()
    broken = J.JudgeSpec(
        name="ghost",
        argv=("nos-judge-that-does-not-exist",),
        adapter="exit_zero",
        pass_exit=(0,),
        fail_exit=(1,),
    )
    registry = J.Registry(
        judges={"ghost": broken},
        gate_sets={"fast": J.GateSetSpec(name="fast", judges=("ghost",))},
    )
    verdict = J.run_gate_set("fast", registry=registry, repo_root=REPO, probe=_always_true)
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert verdict.runs[0].status == "skipped"


def test_an_empty_gate_set_is_indeterminate_not_a_pass():
    """`all([])` is True — the hidden-fee-08 shape, in the aggregator itself.

    A gate set that ran no judges has proved nothing. This is the same bug as
    an empty Docker stack passing a health probe as `0/0 ready`, one layer up.
    """
    registry = J.Registry(
        judges={},
        gate_sets={"empty": J.GateSetSpec(name="empty", judges=())},
    )
    verdict = J.run_gate_set("empty", registry=registry, repo_root=REPO)
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE


def test_a_held_exclusive_resource_is_indeterminate_not_a_pass(tmp_path):
    """M7 — genome-codegen WRITES the file test_genome_contract.py MUTATES.

    There is no lock upstream, so the runner supplies one. A held lock never
    blocks and never runs anyway; it reports "we did not measure this".
    """
    (tmp_path / "nos-loop-nos_entity.lock").write_text("999999\n")
    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("genome-codegen", "fast"),
        repo_root=REPO,
        spawn=_fake_spawn(**{"genome-codegen": GREEN_GENOME}),
        probe=_always_true,
        lock_dir=tmp_path,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE


def test_an_unknown_gate_set_raises_rather_than_verdicting():
    """A typo must not be reportable as either "tree is bad" or "tree is fine"."""
    with pytest.raises(J.ConfigError):
        J.run_gate_set("no-such-set", registry=_registry(), repo_root=REPO)


# ── 3. Two runs agree (determinism) ────────────────────────────────────────


def test_two_runs_of_the_same_tree_agree():
    """Same tree, same inputs → identical digest, twice."""
    kwargs = dict(registry=_registry(), repo_root=REPO, probe=_always_true)
    first = J.run_gate_set("fast", spawn=_green_fast(), **kwargs)
    second = J.run_gate_set("fast", spawn=_green_fast(), **kwargs)
    assert first.result is second.result
    assert first.digest() == second.digest()


def test_a_real_judge_run_twice_agrees():
    """The same property with a REAL subprocess, not a double.

    ``tools/genome-codegen.py --check`` is pure repo I/O and ~2 s. If the digest
    moved between two runs against an unchanged tree, every verdict this engine
    produces would be unreplayable — and §11 makes replay the actual guarantee.
    """
    registry = _one_judge_registry("genome-codegen", "fast")
    first = J.run_gate_set("fast", registry=registry, repo_root=REPO, probe=_always_true)
    second = J.run_gate_set("fast", registry=registry, repo_root=REPO, probe=_always_true)
    assert first.runs[0].status == "exited", first.runs[0].reason
    assert first.result is second.result
    assert first.digest() == second.digest()


def test_the_digest_ignores_wall_clock_but_not_evidence():
    """A digest stable because it hashes nothing would pass the test above.

    Times and sandbox paths are excluded (they vary and are not evidence);
    exit codes, work counts and stdout hashes are included.
    """
    identity = J.run_gate_set(
        "fast", registry=_registry(), repo_root=REPO, spawn=_green_fast(), probe=_always_true
    ).identity()
    blob = str(identity)
    assert "started_at" not in blob and "sandbox_path" not in blob
    assert "1475" in blob and "stdout_sha" in blob


def test_a_different_outcome_changes_the_digest():
    kwargs = dict(registry=_registry(), repo_root=REPO, probe=_always_true)
    green = J.run_gate_set("fast", spawn=_green_fast(), **kwargs)
    red = J.run_gate_set(
        "fast",
        spawn=_fake_spawn(**{"ansible-lint": GREEN_ANSIBLE_LINT, "genome-codegen": STALE_GENOME}),
        **kwargs,
    )
    assert green.digest() != red.digest()


# ── 4. CONSTRAINT A — the proposer can never supply a verdict ──────────────


def test_no_seam_can_supply_a_result():
    """The public API takes a gate set NAME and nothing that means "pass".

    The spawn seam replaces the process (an exit code and bytes); the adapters
    remain the only constructors of a Result. If a caller could hand in a
    result, the verdict would stop being a reward signal and start being an
    output of the thing being rewarded.
    """
    import inspect

    params = set(inspect.signature(J.run_gate_set).parameters)
    forbidden = {"result", "verdict", "outcome", "passed", "status", "force"}
    assert not (params & forbidden), f"run_gate_set accepts a verdict-shaped input: {params}"

    src = JUDGES_PY.read_text(encoding="utf-8")
    # A Result is constructed only by the adapters and the fail-closed paths of
    # the runner — never from parsed caller input.
    assert "Result(" not in src.replace("Result(str, Enum)", ""), (
        "judges.py builds a Result from a dynamic value; a verdict must be "
        "computed from a process, never cast from input"
    )


def test_the_spawn_double_cannot_return_a_verdict():
    """Structural: Completed carries an exit code and bytes, and no result."""
    fields = set(J.Completed.__dataclass_fields__)
    assert fields == {"exit_code", "stdout", "stderr", "timed_out"}, fields


# ── 5. CONSTRAINT B — a step may not record its own success ────────────────


def test_the_run_record_is_open_before_the_process_exists():
    """The record is written by the exit READER, never by the judge.

    Precedent: tests/anatomy/test_post_wiring_is_not_self_reporting.py. The
    v0.10-beta lesson was a notification stamping delivery on failure and a scan
    stamping freshness without scanning — the record must not be authored by the
    code whose success it describes.
    """
    seen: list[str] = []

    def introspecting_spawn(argv, cwd, timeout_s):
        # At this instant the run exists and is UNDECIDED.
        seen.append("spawned")
        return GREEN_GENOME

    verdict = J.run_gate_set(
        "fast",
        registry=_one_judge_registry("genome-codegen", "fast"),
        repo_root=REPO,
        spawn=introspecting_spawn,
        probe=_always_true,
    )
    assert seen == ["spawned"]
    run = verdict.runs[0]
    assert run.status == "exited"
    assert run.started_at is not None and run.finished_at is not None
    assert run.started_at <= run.finished_at

    src = JUDGES_PY.read_text(encoding="utf-8")
    body = src.split("def _spawn_and_read", 1)[1]
    open_at = body.index('status="running"')
    spawn_at = body.index("spawn(spec.argv")
    assert open_at < spawn_at, (
        "the run record must be opened BEFORE the subprocess starts, so a judge "
        "that is killed leaves evidence it ran at all"
    )


def test_work_count_is_parsed_from_the_process_not_supplied():
    """A judge reports its work in its own stdout; nobody hands it a number."""
    import inspect

    params = set(inspect.signature(J.work_count).parameters)
    assert params == {"spec", "done"}, params
    spec = _spec("ansible-lint")
    assert J.work_count(spec, GREEN_ANSIBLE_LINT) == 1475
    assert J.work_count(spec, J.Completed(exit_code=0, stdout="nothing useful")) is None


def test_a_crashed_run_is_never_left_looking_successful():
    run = J.JudgeRun(judge_name="x", gate_set="fast", argv=("x",))
    assert run.status == "running"
    assert run.result is None, "a fresh run must not be born with a verdict"


# ── 6. Honesty about side-effecting judges (DECISIONS 2d/2e/2f) ────────────


def test_pytest_never_runs_against_the_live_tree():
    """DECISION 2d — always sandboxed, attended and unattended alike."""
    seen_cwd: list[str] = []

    def spy(argv, cwd, timeout_s):
        seen_cwd.append(cwd)
        return J.Completed(exit_code=0, stdout="3050 passed in 252.00s\n")

    sandbox = REPO.parent / "fake-sandbox"
    verdict = J.run_gate_set(
        "repo",
        registry=_one_judge_registry("pytest-anatomy", "repo"),
        repo_root=REPO,
        spawn=spy,
        probe=_always_true,
        sandbox_factory=lambda root: (sandbox, "sha-fake", lambda: None),
    )
    assert verdict.result is J.Result.PASS
    assert seen_cwd == [str(sandbox)]
    assert str(REPO) not in seen_cwd, "pytest was run against the operator's live tree"


def test_every_judge_in_a_set_observes_exactly_one_tree():
    """§2.5, against the REAL `repo` set — which is where the defect lived.

    The test above uses a ONE-JUDGE registry, so it could never see the shape it
    was named for: with only `mutates_worktree` judges sandboxed, `repo` linted
    the operator's live (possibly dirty) tree with ansible-lint and
    genome-codegen while pytest-anatomy tested HEAD, and aggregated the two as
    if they described one thing. An uncommitted `.ansible-lint` edit — no
    proposal, no fingerprint, no diff — then turned that judge green everywhere,
    and the sealed verdict named whatever `tree_sha` the caller typed.

    Three judges, one cwd, one recorded sha, and the live tree in neither.
    """
    seen_cwd: list[str] = []

    def spy(argv, cwd, timeout_s):
        seen_cwd.append(cwd)
        return {
            "ansible-lint": GREEN_ANSIBLE_LINT,
            "genome-codegen": GREEN_GENOME,
            "pytest": J.Completed(exit_code=0, stdout="3050 passed in 252.00s\n"),
        }[_argv_key(argv)]

    sandbox = REPO.parent / "one-tree-sandbox"
    verdict = J.run_gate_set(
        "repo",
        registry=_registry(),
        repo_root=REPO,
        spawn=spy,
        probe=_always_true,
        sandbox_factory=lambda root: (sandbox, "0123456789abcdef", lambda: None),
    )
    assert len(verdict.runs) == 3, verdict.runs
    assert set(seen_cwd) == {str(sandbox)}, f"the set observed >1 tree: {set(seen_cwd)}"
    assert str(REPO) not in seen_cwd, "a judge graded the operator's working copy"
    assert {r.tree_sha for r in verdict.runs} == {"0123456789abcdef"}


def test_a_run_records_the_tree_it_judged_and_the_digest_covers_it():
    """§11 makes replay the guarantee — "re-run the recorded argv against the
    recorded tree". Nothing recorded the tree, at any layer: judges.py had no
    `rev-parse`, `JudgeRun.identity()` excluded the sandbox on purpose, and the
    ledger took `tree_sha` as a caller-supplied string. A verdict that cannot
    say what it judged is a claim."""
    registry = _one_judge_registry("genome-codegen", "fast")
    verdict = J.run_gate_set(
        "fast", registry=registry, repo_root=REPO, probe=_always_true,
        spawn=_fake_spawn(**{"genome-codegen": GREEN_GENOME}),
    )
    sha = verdict.runs[0].tree_sha
    assert sha and len(sha) == 40, f"the sandbox did not name its commit: {sha!r}"
    assert "tree_sha" in verdict.runs[0].identity()
    assert sha in str(verdict.identity())


def test_a_sandbox_that_will_not_name_its_commit_is_not_a_tree():
    """The real factory reads the sha back OUT of the created worktree. If that
    read fails the sandbox is torn down and the set is INDETERMINATE — a tree
    with no identity is worth less than no tree, because judges would still run
    in it."""
    import subprocess as _sp

    real = J.git_worktree_sandbox
    path, sha, cleanup = real(REPO)
    try:
        assert sha == _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO),
            capture_output=True, text=True, check=True).stdout.strip()
        assert (path / ".git").exists()
    finally:
        cleanup()
    assert not path.exists(), "the sandbox outlived its cleanup"


def test_a_sandbox_that_cannot_be_created_is_indeterminate_not_a_pass():
    """If the sandbox fails, the judge does not fall back to the live tree.

    test_genome_contract.py appends HAND_EDITED to a TRACKED file and restores
    it in a `finally`; a killed run leaves that source corrupted. Falling back
    would put the operator's uncommitted work behind that risk.
    """
    def failing_sandbox(root):
        raise J.SandboxError("git worktree add failed: fatal: not a working tree")

    ran: list = []

    verdict = J.run_gate_set(
        "repo",
        registry=_one_judge_registry("pytest-anatomy", "repo"),
        repo_root=REPO,
        spawn=lambda *a: ran.append(a) or J.Completed(exit_code=0, stdout="250 passed"),
        probe=_always_true,
        sandbox_factory=failing_sandbox,
    )
    assert verdict.result is not J.Result.PASS
    assert verdict.result is J.Result.INDETERMINATE
    assert ran == [], "the judge ran even though its sandbox could not be created"


def test_the_sandbox_is_cleaned_up_even_when_the_judge_fails():
    cleaned: list[str] = []

    def sandbox(root):
        return REPO, "sha-fake", lambda: cleaned.append("cleaned")

    J.run_gate_set(
        "repo",
        registry=_one_judge_registry("pytest-anatomy", "repo"),
        repo_root=REPO,
        spawn=_fake_spawn(**{"pytest": J.Completed(exit_code=1, stdout="3 failed, 247 passed")}),
        probe=_always_true,
        sandbox_factory=sandbox,
    )
    assert cleaned == ["cleaned"]


def test_committed_argv_pins_the_side_effect_suppressing_flags():
    """DECISION 2e — the flags are part of the committed argv, not runtime hope.

    Without --no-jsonl, nos-smoke appends to ~/.nos/events/smoke.jsonl, OUTSIDE
    the repo, where `git status` can never reveal it. Without --no-ledger,
    corpus-diff advances or zeroes agreeStreak, may page the operator via A9,
    and may run --halt-cmd, stopping the organ's fs-sync. A judge that can page
    the operator and halt an organ is not a judge.
    """
    reg = _registry()
    assert "--no-jsonl" in reg.judges["nos-smoke"].argv
    corpus = reg.judges["cortex-corpus-diff"].argv
    assert "--no-ledger" in corpus and "--json" in corpus


def test_keap_lint_is_not_a_judge_in_any_gate_set():
    """DECISION 2f — it needs a RW token, POSTs /lint/run which reconciles
    state, pages via A9, and its exit 0 means "ran", not "clean".

    That is a scheduled maintenance job with an alerting side effect. Admitting
    it would give the loop a judge that mutates the thing being measured.
    """
    reg = _registry()
    assert "keap-lint" not in reg.judges
    for name, gs in reg.gate_sets.items():
        assert "keap-lint" not in gs.judges, f"keap-lint admitted to {name}"


def test_every_judge_that_mutates_the_worktree_says_so():
    """A judge that mutates the tree without declaring it gets no sandbox."""
    reg = _registry()
    assert reg.judges["pytest-anatomy"].mutates_worktree is True
    # M7: both writers of nos_entity.py must share one exclusive resource.
    assert reg.judges["pytest-anatomy"].exclusive_resource == "nos_entity"
    assert reg.judges["genome-codegen"].exclusive_resource == "nos_entity"


#: MEASURED, and every entry has a transcript. The gate that carried this claim
#: asserted two of five and skipped the one that did not hold — pytest-anatomy
#: sat at min_work 200 against 2428 executed tests, 12x below reality, unable to
#: notice a 91% scope loss. A ratchet nobody checks is a comment.
#:
#:   ansible-lint    "in 1475 files processed of 3147 encountered"   EXIT=0
#:   genome-codegen  "genome artifacts current (2 checked)"          EXIT=0
#:   pytest-anatomy  "2456 passed, 4 skipped in 194.76s"   (2026-08-02, this tree)
#:   nos-smoke       len(state/smoke-catalog.yml: smoke_endpoints)   — see below
#:   corpus-diff     one table compared is the floor for a diff
#: RE-MEASURED 2026-08-05: ansible-lint "in 1463 files processed of 3133
#: encountered" EXIT=0; pytest-anatomy "2788 passed, 25 skipped in 228.85s".
#: Re-measured 2026-08-06 on this tree, both by running the tools:
#:   pytest tests/anatomy -q  → "2911 passed, 25 skipped"
#:   ansible-lint             → "0 failure(s) ... in 1475 files processed of 3147"
#: The pytest number moved because the gate below FORCED it: the suite had
#: grown to 2936 collected against a 2788 record, and a ratchet left behind by
#: growth certifies a fraction of the suite it names. That is the second way a
#: ratchet rots and the only one a file-vs-file comparison cannot see.
#: RE-DERIVED 2026-08-06 (second time that day): "2943 passed, 26 skipped" after
#: the anatomy-graph gate landed (+19 tests, plus unrelated growth). The
#: collection gate below did NOT fire this time — 2943 against a 2911 record
#: was inside its 5% allowance — but a record known stale is re-derived anyway:
#: the allowance is slack for host variance, not a budget to spend.
#: RE-DERIVED 2026-08-06 (fourth pass that day), both by running the tools:
#:   pytest tests/anatomy -q  → "3050 passed, 27 skipped in 252s"
#:   ansible-lint             → "0 failure(s) ... in 1489 files processed of 3193"
#: RE-DERIVED 2026-08-07 after R1 (service→service dependency edges, +11 tests),
#: both by running the tools:
#:   pytest tests/anatomy -q  → "3061 passed, 27 skipped in 253s"
#:   ansible-lint             → "0 failure(s) ... in 1495 files processed of 3227"
#: The collection gate did NOT fire (3050 against 3088 collected is inside its
#: 5% allowance) — re-derived anyway, because a record known stale is stale.
MEASURED_WORK = {
    "ansible-lint": 1495,
    "genome-codegen": 2,
    "pytest-anatomy": 3061,
    "cortex-corpus-diff": 1,
}


def test_the_ratchets_match_measured_reality():
    """The ratchet records TODAY's scope so tomorrow's cannot silently shrink.

    Every judge is asserted, not a chosen subset: the one this gate used to skip
    is the one that was wrong. The floor may sit at or just below the
    measurement (host-conditional skips are real); it may not sit an order of
    magnitude below it, which is what "cannot silently shrink" means.
    """
    reg = _registry()
    assert set(MEASURED_WORK) | {"nos-smoke"} == set(reg.judges), (
        "a judge was added or removed without re-measuring its ratchet: "
        f"{set(reg.judges) ^ (set(MEASURED_WORK) | {'nos-smoke'})}"
    )
    for name, measured in MEASURED_WORK.items():
        floor = reg.judges[name].min_work
        assert floor <= measured, f"{name}: min_work {floor} exceeds measured {measured}"
        assert floor >= measured * 0.95, (
            f"{name}: min_work {floor} is {measured / max(floor, 1):.1f}x below the "
            f"measured {measured} — that gap is the ratchet's own scope loss"
        )

    # nos-smoke's floor is DERIVED from its catalog rather than transcribed, so
    # the two cannot drift apart. That catalog is this judge's own oracle (§5.1),
    # so a proposal cannot lower the floor by emptying the catalog.
    catalog = yaml.safe_load(
        (REPO / "state" / "smoke-catalog.yml").read_text(encoding="utf-8"))
    entries = len(catalog["smoke_endpoints"])
    assert reg.judges["nos-smoke"].min_work == entries, (
        f"nos-smoke min_work={reg.judges['nos-smoke'].min_work} but the committed "
        f"catalog declares {entries} probes — at 1, the catalog could shrink to a "
        f"single probe and still read PASS (only literal zero was caught)"
    )

    assert all(j.min_work >= 1 for j in reg.judges.values()), (
        "a min_work of 0 disables the ratchet and re-opens the zero-work false green"
    )


def test_the_pytest_ratchet_is_remeasured_against_collection():
    """A ratchet that only compares committed numbers decays as the suite grows.

    The gate above pins `min_work` to `MEASURED_WORK`, and both live in this
    repo. That catches a floor set too low against the measurement of the day.
    It cannot catch the other direction, and the other direction is what
    happened: floor 2400, measurement 2456 from 2026-08-02, real suite 2788 by
    2026-08-05. Neither number moved, both still agreed with each other, and a
    run that had lost 14% of its collection cleared the floor. Same defect as
    the 12x gap the comment in judge-sets.yml warns about — reached by growth
    rather than by a guess, which is why nothing noticed.

    So this one asks the suite instead of the file. `--collect-only` is the
    cheap question (~7s, no test bodies run) and counts skips, which executed
    work does not — hence the 5% allowance rather than equality.

    nos-smoke does not need this: its floor is DERIVED from its catalog, so the
    two cannot drift apart in either direction. That is the better shape, and
    pytest cannot have it directly — collection is not a committed artifact —
    but it can be forced to re-derive.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/anatomy", "--collect-only", "-q"],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    assert match, (
        "could not read a collection count from pytest; this gate has gone "
        f"blind rather than green.\nstdout tail: {proc.stdout[-500:]}"
    )
    collected = int(match.group(1))
    assert collected > 1000, f"collection returned {collected} — the run is broken, not the ratchet"

    recorded = MEASURED_WORK["pytest-anatomy"]
    assert recorded >= collected * 0.95, (
        f"tests/anatomy now collects {collected} tests but the recorded "
        f"measurement is {recorded}, a {1 - recorded / collected:.0%} gap. The "
        f"ratchet has decayed by growth: re-run `pytest tests/anatomy -q`, put "
        f"the passed count here, and raise min_work in state/judge-sets.yml to "
        f"just below it. Leaving it is how a judge comes to certify a fraction "
        f"of the suite it names."
    )


def test_the_registry_is_literal_yaml_with_no_jinja():
    """CONSTRAINT G, defensively: this file must never enter a template path."""
    text = REGISTRY_YML.read_text(encoding="utf-8")
    assert "{{" not in text and "{%" not in text
    assert isinstance(yaml.safe_load(text), dict)


def test_cli_exit_codes_are_a_fixed_enum_not_a_count():
    """DECISION 6a — explicitly not nos-smoke's exit-as-count, and INDETERMINATE
    is separated from FAIL at the shell boundary so a wrapper cannot collapse
    them."""
    assert J.CLI_EXIT == {
        "pass": 0,
        "fail": 1,
        "indeterminate": 2,
        "refused": 3,
        "config_error": 4,
    }
