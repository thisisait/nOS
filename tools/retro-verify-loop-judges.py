#!/usr/bin/env python3
"""Retro-verification harness for the judge-runner gates (constraint C).

"A gate you can satisfy by editing the gate is not one. Every gate must be
RETRO-VERIFIED: reintroduce the defect, watch it go red, restore."

For each defect below this script:
  1. reintroduces it by an exact string substitution in the real source,
  2. runs the specific test that is supposed to catch it,
  3. asserts that test went RED,
  4. restores the file byte-for-byte and re-asserts GREEN.

Any mutation that does NOT go red is reported as DECORATION — a gate that
cannot fail is not evidence of anything. The script exits non-zero if any gate
is decoration, or if the tree is not restored exactly.

Usage:  python3 tools/retro-verify-loop-judges.py
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
JUDGES = REPO / "files" / "anatomy" / "bone" / "judges.py"
REGISTRY = REPO / "state" / "judge-sets.yml"
TESTFILE = "tests/anatomy/test_loop_judge_runner.py"

# (label, file, old, new, test node that MUST go red)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, str]] = [
    (
        "empty gate set reads as success (`all([])` is True)",
        JUDGES,
        """    runs = list(runs)
    if not runs:
        return GateSetVerdict(
            gate_set=gate_set,
            result=Result.INDETERMINATE,
            runs=[],
            reason="gate set ran no judges — absence is not success",
        )""",
        """    runs = list(runs)
    if not runs:
        return GateSetVerdict(
            gate_set=gate_set, result=Result.PASS, runs=[], reason="nothing to do"
        )""",
        "test_an_empty_gate_set_is_indeterminate_not_a_pass",
    ),
    (
        "work ratchet removed — zero work reads as success",
        JUDGES,
        """    if result is Result.PASS:
        if run.work is None:""",
        """    if False:
        if run.work is None:""",
        "test_nos_smoke_zero_entries_is_not_a_pass",
    ),
    (
        "work ratchet removed — all-skipped pytest reads as success",
        JUDGES,
        """    if result is Result.PASS:
        if run.work is None:""",
        """    if False:
        if run.work is None:""",
        "test_pytest_all_skipped_is_not_a_pass",
    ),
    (
        "work ratchet removed — shrunken ansible-lint scope reads as success",
        JUDGES,
        """    if result is Result.PASS:
        if run.work is None:""",
        """    if False:
        if run.work is None:""",
        "test_work_below_the_ratchet_is_not_a_pass",
    ),
    (
        "judge runs degraded when its requirements are absent (DECISION 2c)",
        JUDGES,
        """    missing = [r for r in spec.requires if not probe(r)]
    if missing:""",
        """    missing = []
    if missing:""",
        "test_absent_requirement_is_indeterminate_and_the_judge_never_runs",
    ),
    (
        "naive exit adapter — unknown exit code guessed as FAIL",
        JUDGES,
        """    if done.exit_code in spec.fail_exit:
        return Result.FAIL, f"exit {done.exit_code} in fail_exit"
    return Result.INDETERMINATE, (""",
        """    if done.exit_code != 0:
        return Result.FAIL, f"exit {done.exit_code} nonzero"
    return Result.INDETERMINATE, (""",
        "test_an_unknown_exit_code_is_indeterminate_not_a_pass",
    ),
    (
        "constraint B — the run records its own success before the process runs",
        JUDGES,
        """        status="running",
        result=None,""",
        """        status="exited",
        result=Result.PASS,""",
        # Targets the SOURCE-ORDER gate, not the dataclass-default gate. The
        # first draft aimed this at test_a_crashed_run_is_never_left_looking_
        # successful, which constructs a JudgeRun directly and therefore never
        # sees a change at this call site — it stayed green. Behaviourally this
        # mutation is currently invisible (every exit path overwrites the
        # value), so a structural gate is the honest one for it.
        "test_the_run_record_is_open_before_the_process_exists",
    ),
    (
        "constraint B — a JudgeRun is born already claiming to have passed",
        JUDGES,
        """    status: str = "running"  # running | exited | crashed | skipped
    result: Result | None = None""",
        """    status: str = "exited"  # running | exited | crashed | skipped
    result: Result | None = Result.PASS""",
        "test_a_crashed_run_is_never_left_looking_successful",
    ),
    (
        "killed judge (no exit status) reads as success",
        JUDGES,
        """    if done.timed_out or done.exit_code is None:""",
        """    if False:""",
        "test_a_killed_judge_is_indeterminate_not_a_pass",
    ),
    (
        "sandbox failure falls back to the operator's live tree",
        JUDGES,
        """        except Exception as exc:  # noqa: BLE001 — any sandbox failure is INDETERMINATE
            return _skipped(""",
        """        except Exception as exc:  # noqa: BLE001
            cwd, cleanup = repo_root, None
            _unused = lambda: _skipped(""",
        "test_a_sandbox_that_cannot_be_created_is_indeterminate_not_a_pass",
    ),
    (
        "corpus-diff verdict read from the exit code instead of .agrees",
        JUDGES,
        """    report = _parse_json_report(done.stdout)
    if report is None:
        return Result.INDETERMINATE, (""",
        """    if done.exit_code == 0:
        return Result.PASS, "exit 0"
    report = _parse_json_report(done.stdout)
    if report is None:
        return Result.INDETERMINATE, (""",
        "test_corpus_diff_exit_zero_while_disagreeing_is_a_fail_not_a_pass",
    ),
    (
        # TWO substitutions on purpose. This property is defended in depth: the
        # adapter refuses an unparseable report AND the work ratchet refuses a
        # PASS it cannot evidence. Breaking only the adapter left the test green
        # because the ratchet still caught it — true, but it meant the mutation
        # was not reintroducing the defect, only half of it. The honest
        # reintroduction disables both layers; if the test still passed then,
        # the property would genuinely be unguarded.
        "corpus-diff VOID night (no JSON, exit 0) reads as success "
        "[adapter + ratchet both disabled]",
        JUDGES,
        (
            """    report = _parse_json_report(done.stdout)
    if report is None:
        return Result.INDETERMINATE, (""",
            """    if result is Result.PASS:
        if run.work is None:""",
        ),
        (
            """    if done.exit_code == 0:
        return Result.PASS, "exit 0"
    report = _parse_json_report(done.stdout)
    if report is None:
        return Result.INDETERMINATE, (""",
            """    if False:
        if run.work is None:""",
        ),
        "test_corpus_diff_void_night_is_indeterminate_not_a_pass",
    ),
    (
        "pytest work count includes SKIPPED as work",
        JUDGES,
        """        return (
            counts.get("passed", 0)
            + counts.get("failed", 0)
            + counts.get("error", 0)
            + counts.get("errors", 0)
        )""",
        """        return sum(counts.values())""",
        "test_pytest_all_skipped_is_not_a_pass",
    ),
    (
        "held exclusive-resource lock ignored (M7 — concurrent writers)",
        JUDGES,
        """            except _ResourceBusy as exc:
                return _skipped(""",
        """            except _ResourceBusy as exc:
                _unused = lambda: _skipped(""",
        "test_a_held_exclusive_resource_is_indeterminate_not_a_pass",
    ),
    (
        "a FAIL masked by an INDETERMINATE in the same set",
        JUDGES,
        """    fails = [r for r in runs if r.result is Result.FAIL]
    if fails:""",
        """    fails = [] if any(r.result is Result.INDETERMINATE for r in runs) else [
        r for r in runs if r.result is Result.FAIL
    ]
    if fails:""",
        "test_a_fail_outranks_an_indeterminate",
    ),
    (
        "digest hashes wall-clock time — verdicts stop being reproducible",
        JUDGES,
        """            "stdout_sha": self.stdout_sha,
        }""",
        """            "stdout_sha": self.stdout_sha,
            "started_at": self.started_at,
        }""",
        "test_a_real_judge_run_twice_agrees",
    ),
    (
        "constraint A — a caller-supplied result parameter is added",
        JUDGES,
        """def run_gate_set(
    gate_set: str,
    *,
    registry: Registry | None = None,""",
        """def run_gate_set(
    gate_set: str,
    *,
    result: str | None = None,
    registry: Registry | None = None,""",
        "test_no_seam_can_supply_a_result",
    ),
    (
        "registry — nos-smoke loses its --no-jsonl side-effect suppressor",
        REGISTRY,
        '''    argv: ["python3", "tools/nos-smoke.py", "--no-jsonl"]''',
        '''    argv: ["python3", "tools/nos-smoke.py"]''',
        "test_committed_argv_pins_the_side_effect_suppressing_flags",
    ),
    (
        "registry — corpus-diff loses --no-ledger (can page + halt an organ)",
        REGISTRY,
        '''    argv: ["python3", "files/anatomy/scripts/cortex-corpus-diff.py", "--no-ledger", "--json"]''',
        '''    argv: ["python3", "files/anatomy/scripts/cortex-corpus-diff.py", "--json"]''',
        "test_committed_argv_pins_the_side_effect_suppressing_flags",
    ),
    (
        "registry — the ansible-lint scope ratchet is disarmed (1400 -> 0)",
        REGISTRY,
        """    min_work: 1400""",
        """    min_work: 0""",
        "test_the_ratchets_match_measured_reality",
    ),
    (
        "registry — keap-lint admitted as a judge (RW token, reconciles, pages)",
        REGISTRY,
        """  fast:
    judges: ["ansible-lint", "genome-codegen"]""",
        """  fast:
    judges: ["ansible-lint", "genome-codegen", "keap-lint"]""",
        "test_keap_lint_is_not_a_judge_in_any_gate_set",
    ),
    (
        "registry — pytest-anatomy stops declaring that it mutates the worktree",
        REGISTRY,
        """    mutates_worktree: true""",
        """    mutates_worktree: false""",
        "test_pytest_never_runs_against_the_live_tree",
    ),
    (
        "registry — a Jinja brace sequence enters the literal-data file",
        REGISTRY,
        """version: 1""",
        """version: 1
# {{ global_password_prefix }}_pw_loop""",
        "test_the_registry_is_literal_yaml_with_no_jinja",
    ),
]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_bytecode(path: pathlib.Path) -> None:
    """Delete cached bytecode for a mutated source file.

    THIS IS LOAD-BEARING, and it was found the hard way. A .pyc is validated
    against its source by (mtime, size) — and mtime is stored with ONE SECOND
    of resolution. Two different mutations of judges.py happened to change the
    file by exactly +6 bytes each, so when the second was written inside the
    same second as the first, the interpreter revalidated the FIRST mutation's
    bytecode as current and ran it. The test then passed against code that was
    never loaded, and this harness reported the gate as decoration —
    intermittently, roughly one run in three.

    That is the same defect class this whole engine exists to refuse: a step
    reporting on an effect it did not verify. A retro-verification harness that
    can silently test stale bytecode is worth less than no harness, because it
    produces confident wrong answers.
    """
    cache = path.parent / "__pycache__"
    if cache.is_dir():
        for pyc in cache.glob(f"{path.stem}.*.pyc"):
            pyc.unlink(missing_ok=True)


def run_test(node: str) -> tuple[bool, str]:
    target = f"{TESTFILE}::{node}" if node else TESTFILE
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-x"],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode == 0, (tail[-1] if tail else "(no output)")


def main() -> int:
    baseline = {JUDGES: (JUDGES.read_text(), sha(JUDGES)),
                REGISTRY: (REGISTRY.read_text(), sha(REGISTRY))}

    ok, line = run_test("")
    print(f"BASELINE  whole file: {'GREEN' if ok else 'RED'}  |  {line}\n")
    if not ok:
        print("baseline is not green — refusing to retro-verify against a red tree")
        return 4

    decoration: list[str] = []
    print(f"{'#':>3}  {'result':<12} gate / reintroduced defect")
    print("-" * 100)

    for i, (label, path, old, new, node) in enumerate(MUTATIONS, 1):
        original, original_sha = baseline[path]
        # A mutation may be a single (old, new) or a tuple of each, when the
        # defect only exists if several defence layers are broken together.
        olds = old if isinstance(old, tuple) else (old,)
        news = new if isinstance(new, tuple) else (new,)
        if any(o not in original for o in olds):
            print(f"{i:>3}  {'ANCHOR-LOST':<12} {label}")
            decoration.append(f"{label} (mutation anchor no longer matches source)")
            continue
        try:
            mutated = original
            for o, n in zip(olds, news):
                mutated = mutated.replace(o, n, 1)
            path.write_text(mutated)
            purge_bytecode(path)
            went_red, line = run_test(node)
            went_red = not went_red
        finally:
            path.write_text(original)
            purge_bytecode(path)
            assert sha(path) == original_sha, f"RESTORE FAILED for {path}"

        status = "RED (good)" if went_red else "STAYED GREEN"
        print(f"{i:>3}  {status:<12} {label}")
        print(f"     {'':<12} -> {node}")
        print(f"     {'':<12}    {line}")
        if not went_red:
            decoration.append(f"{label} -> {node}")

    print("-" * 100)
    for path, (_, original_sha) in baseline.items():
        assert sha(path) == original_sha, f"tree not restored: {path}"
    print("tree restored byte-for-byte (sha256 verified on both files)")

    ok, line = run_test("")
    print(f"AFTER     whole file: {'GREEN' if ok else 'RED'}  |  {line}")
    if not ok:
        return 4

    if decoration:
        print("\nDECORATION — these gates did not go red when their defect was reintroduced:")
        for d in decoration:
            print(f"  - {d}")
        return 1
    print(f"\nall {len(MUTATIONS)} reintroduced defects were caught; no decoration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
