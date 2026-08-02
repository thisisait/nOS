#!/usr/bin/env python3
"""Retro-verification harness for the loop's CAPTURE defects.

Constraint C: "a gate you can satisfy by editing the gate is not one. Every gate
you write must be RETRO-VERIFIED: reintroduce the defect, watch it go red,
restore." A gate that was never seen to fail is decoration.

Sibling of ``tools/retro-verify-loop-harness.py``, which retro-verifies the
cross-harness determinism gate. This one covers the eight defects found by an
adversarial review of the engine core — every one of which was *reproduced
end-to-end* against the real modules before it was fixed, and every one of which
is a capture path rather than a crash:

  1. `seal_verdict` let its caller choose which judge runs counted, so a PASS
     could be assembled from a green subset while a FAIL sat on record, or from
     an unrelated proposal's runs at an unrelated tree.
  2. `expected_judges` was caller-supplied, so `[]` made the missing-judge
     guard vacuous.
  3. §4's retry ceiling was keyed on two fields the proposer declares, so a
     fresh nonce bought unlimited attempts against judges the registry itself
     marks non-deterministic.
  4. Judges in one gate set observed two different trees, neither verified, so
     an uncommitted `.ansible-lint` edit silenced a judge with no proposal.
  5. The pytest adapter ignored the exit code, so a judge interrupted 20% of the
     way through read PASS.
  6. The `min_work` ratchets did not match measured reality (200 against 2428;
     1 against a 9-entry catalog), so a 91% scope loss cleared them.
  7. The budget's deny rules were case-sensitive on a case-insensitive
     filesystem, so `roles/pazny.Bone/**` was allowed.
  8. The budget validated the proposer's DECLARED paths and never the diff, so
     every §5 refusal was bypassable by misdeclaring.

For each mutation this script:
  1. reintroduces the defect by an exact string substitution in the real source,
  2. runs the one test node that is supposed to catch it,
  3. asserts that node went RED,
  4. restores the file byte-for-byte and re-asserts the sha256.

Any mutation that does NOT go red is reported as DECORATION and the script
exits non-zero.

Usage:  python3 tools/retro-verify-loop-capture.py
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BONE = REPO / "files" / "anatomy" / "bone"

JUDGES = BONE / "judges.py"
LEDGER = BONE / "ledger.py"
BUDGET = BONE / "budget.py"
REGISTRY = REPO / "state" / "judge-sets.yml"

T_LEDGER = "tests/anatomy/test_loop_ledger.py"
T_RUNNER = "tests/anatomy/test_loop_judge_runner.py"
T_BUDGET = "tests/anatomy/test_loop_budget_forbids_its_own_gates.py"

#: Every gate file this harness claims to have verified. The baseline of ALL of
#: them must be green before a single mutation is applied, and green again
#: after — otherwise a "RED (good)" could be a tree that was already red.
TESTFILES = (T_LEDGER, T_RUNNER, T_BUDGET)

# (label, file, old, new, "testfile::node" that MUST go red)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, str]] = [
    # ── 1. seal_verdict chooses its own evidence ─────────────────────────────
    (
        "the verdict aggregates only the runs that did not fail — a cherry-picked "
        "subset, which is what a caller-supplied `run_uuids` amounted to",
        LEDGER,
        """            if r["uuid"] not in consumed]""",
        """            if r["uuid"] not in consumed and r["outcome"] != "fail"]""",
        f"{T_LEDGER}::test_ADVERSARIAL_a_fail_on_record_cannot_be_left_out_of_the_verdict",
    ),
    (
        "run rows are fetched without the proposal filter, so another proposal's "
        "green run seals this one (rows used to be fetched by uuid alone)",
        LEDGER,
        """            "SELECT * FROM loop_judge_runs WHERE gate_set = ? AND proposal_id IS ? \"""",
        """            "SELECT * FROM loop_judge_runs WHERE gate_set = ? AND (proposal_id IS ? OR 1=1) \"""",
        f"{T_LEDGER}::test_ADVERSARIAL_a_green_run_cannot_be_reattached_to_another_proposal",
    ),
    (
        "evidence is no longer consumed once, so an earlier attempt's greens "
        "re-seal a later attempt",
        LEDGER,
        """        consumed = self._sealed_run_uuids()""",
        """        consumed = set()""",
        f"{T_LEDGER}::test_ADVERSARIAL_the_same_run_cannot_be_sealed_twice",
    ),
    # ── 2. expected_judges is derived, not supplied ──────────────────────────
    (
        "the gate set's membership comes back empty — exactly what a caller "
        "passing `expected_judges=[]` produced, and the missing-judge guard is "
        "then vacuous",
        LEDGER,
        """        expected = list(self._registry().gate_set(gate_set).judges)""",
        """        expected = []""",
        f"{T_LEDGER}::test_a_judge_that_never_reported_makes_the_set_indeterminate",
    ),
    # ── 3. §4's ceiling is keyed on what the SOURCE says ─────────────────────
    (
        "an unknown weakness_id resolves to an empty sha instead of a refusal, "
        "so inventing an id mints a fresh fingerprint and a fresh ceiling",
        LEDGER,
        """            return self.__weakness_cache[str(weakness_id)]""",
        """            return self.__weakness_cache.get(str(weakness_id), "")""",
        f"{T_LEDGER}::test_ADVERSARIAL_an_invented_weakness_id_is_refused_not_treated_as_new",
    ),
    (
        "the lift key stops coming from the weakness reader, so prior attempts "
        "never match and every attempt is attempt 1",
        LEDGER,
        """        priors = self._live_priors(fp, self._weakness_evidence_sha(weakness_id))""",
        """        priors = self._live_priors(fp, "")""",
        f"{T_LEDGER}::test_ADVERSARIAL_a_fresh_nonce_does_not_buy_a_fresh_attempt",
    ),
    (
        "the proposal records a lift key the reader never produced",
        LEDGER,
        """        weakness_evidence_sha = self._weakness_evidence_sha(weakness_id)""",
        """        weakness_evidence_sha = "whatever-the-proposer-likes\"""",
        f"{T_LEDGER}::test_the_evidence_sha_on_the_row_is_the_readers_not_the_proposals",
    ),
    # ── 4. one set, one tree ─────────────────────────────────────────────────
    (
        "per-judge sandboxing returns: only `mutates_worktree` judges get the "
        "sandbox, so a set aggregates judges that read two different trees",
        JUDGES,
        """                    sandbox=Path(cwd),
                    tree_sha=tree_sha,""",
        """                    sandbox=Path(cwd) if spec.mutates_worktree else root,
                    tree_sha=tree_sha,""",
        f"{T_RUNNER}::test_every_judge_in_a_set_observes_exactly_one_tree",
    ),
    (
        "the run stops recording the commit it judged — §11's replay then has no "
        "tree to re-run against",
        JUDGES,
        """        sandbox_path=str(cwd),
        tree_sha=tree_sha,""",
        """        sandbox_path=str(cwd),
        tree_sha=None,""",
        f"{T_RUNNER}::test_a_run_records_the_tree_it_judged_and_the_digest_covers_it",
    ),
    (
        "the ledger stops noticing that its judges disagree about which tree "
        "they read",
        LEDGER,
        """        if tree_reason and result != "fail":""",
        """        if False:""",
        f"{T_LEDGER}::test_ADVERSARIAL_judges_that_saw_two_trees_cannot_pass",
    ),
    # ── 5. the pytest adapter reads the exit code ────────────────────────────
    (
        "the pytest adapter ignores the exit code again — a judge killed 20% of "
        "the way through prints a pass-shaped summary and exits 2",
        JUDGES,
        """    if done.exit_code != 0:
        return Result.INDETERMINATE, (""",
        """    if False:
        return Result.INDETERMINATE, (""",
        f"{T_RUNNER}::test_an_interrupted_pytest_is_not_a_pass",
    ),
    (
        "a genuinely failing interrupted run is downgraded to INDETERMINATE — "
        "the ordering rule of DECISION 2b, inverted, which HIDES a red",
        JUDGES,
        """    if failed:
        return Result.FAIL, f"{failed} failing test(s)\"""",
        """    if failed and done.exit_code == 1:
        return Result.FAIL, f"{failed} failing test(s)\"""",
        f"{T_RUNNER}::test_an_interrupted_pytest_that_did_fail_is_still_a_fail",
    ),
    # ── 6. the ratchets record measured reality ──────────────────────────────
    (
        "pytest-anatomy's ratchet goes back to 200 against 2428 executed tests — "
        "12x below reality, unable to see a 91% scope loss",
        REGISTRY,
        """    min_work: 2400""",
        """    min_work: 200""",
        f"{T_RUNNER}::test_the_ratchets_match_measured_reality",
    ),
    (
        "nos-smoke's ratchet goes back to 1, so the catalog can shrink to a "
        "single probe and still read PASS",
        REGISTRY,
        """    min_work: 9""",
        """    min_work: 1""",
        f"{T_RUNNER}::test_the_ratchets_match_measured_reality",
    ),
    # ── 7. the budget is case-blind on a case-insensitive filesystem ─────────
    (
        "budget comparisons stop folding case, so `roles/pazny.Bone/**` is "
        "allowed and resolves to the engine's own Ansible role",
        BUDGET,
        """    return _normalize(path).casefold()""",
        """    return _normalize(path)""",
        f"{T_BUDGET}::test_a_capital_letter_does_not_lift_a_deny_rule",
    ),
    (
        "the §5a carve-out's never-list goes back to a case-sensitive basename "
        "compare, so `tests/anatomy/Conftest.py` — the file that decides which "
        "gates run — becomes gate-add exempt",
        BUDGET,
        """    folded = _fold(path)
    if not folded.startswith(_GATE_ADD_ROOT.casefold()):""",
        """    folded = _normalize(path)
    if not folded.startswith(_GATE_ADD_ROOT):""",
        f"{T_BUDGET}::test_the_gate_add_carve_out_never_list_is_case_folded_too",
    ),
    (
        "the same case-blindness, measured at the ENFORCEMENT site rather than "
        "in the pure function — a 409 that never fires is not a rule",
        BUDGET,
        """    return _normalize(path).casefold()""",
        """    return _normalize(path)""",
        f"{T_BUDGET}::test_the_case_variant_is_refused_at_the_enforcement_site",
    ),
    # ── 8. the budget judges the artifact, not the claim ─────────────────────
    (
        "the diff's own paths are no longer read, so a patch rewriting "
        "state/judge-sets.yml passes by being declared as a role file",
        BUDGET,
        """    from_diff = diff_paths(diff_text) if diff_text else []""",
        """    from_diff = []""",
        f"{T_BUDGET}::test_a_diff_that_edits_a_forbidden_path_is_refused_however_it_is_declared",
    ),
    (
        "diff-derived paths are reported but not rule-checked — the refusal "
        "names them and then lets them through",
        BUDGET,
        """    raw_paths: Sequence[str] = declared + undeclared""",
        """    raw_paths: Sequence[str] = declared""",
        f"{T_BUDGET}::test_a_diff_that_edits_a_forbidden_path_is_refused_however_it_is_declared",
    ),
    (
        "`diff --git` renames stop being read, so the OLD path of a rename is "
        "invisible to the budget",
        BUDGET,
        """        m = _DIFF_GIT_RE.match(line)
        if m:""",
        """        m = None
        if m:""",
        f"{T_BUDGET}::test_diff_paths_reads_both_spellings_and_ignores_dev_null "
        f"{T_BUDGET}::test_a_pure_rename_out_of_a_forbidden_path_is_refused",
    ),
    (
        "the undeclared-path refusal never reaches the proposer (the ledger is "
        "the enforcement site; the pure function is not)",
        BUDGET,
        """    undeclared = [p for p in from_diff if _fold(p) not in declared_keys]""",
        """    undeclared = []""",
        f"{T_BUDGET}::test_the_undeclared_path_refusal_reaches_the_proposer",
    ),
]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_bytecode(path: pathlib.Path) -> None:
    """Delete cached bytecode for a mutated source file.

    LOAD-BEARING, and learned the hard way by the sibling harness: a .pyc is
    validated against its source by (mtime, size), and mtime has ONE SECOND of
    resolution. Two mutations of the same size written inside one second let the
    interpreter revalidate the FIRST mutation's bytecode as current — the test
    then passes against code that was never loaded, and this harness reports a
    live gate as decoration, intermittently.
    """
    cache = path.parent / "__pycache__"
    if cache.is_dir():
        for pyc in cache.glob(f"{path.stem}.*.pyc"):
            pyc.unlink(missing_ok=True)


def run_test(target: str) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *target.split(), "-q", "--no-header", "-x"],
        cwd=REPO, capture_output=True, text=True, env=env,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode == 0, (tail[-1] if tail else "(no output)")


def main() -> int:
    files = sorted({m[1] for m in MUTATIONS}, key=str)
    baseline = {p: (p.read_text(), sha(p)) for p in files}

    whole = " ".join(TESTFILES)
    ok, line = run_test(whole)
    print(f"BASELINE  {len(TESTFILES)} gate files: {'GREEN' if ok else 'RED'}  |  {line}\n")
    if not ok:
        print("baseline is not green — refusing to retro-verify against a red tree")
        return 4

    decoration: list[str] = []
    print(f"{'#':>3}  {'result':<12} gate / reintroduced defect")
    print("-" * 100)

    for i, (label, path, old, new, node) in enumerate(MUTATIONS, 1):
        original, original_sha = baseline[path]
        if old not in original:
            print(f"{i:>3}  {'ANCHOR-LOST':<12} {label}")
            decoration.append(f"{label} (mutation anchor no longer matches source)")
            continue
        mutated = original.replace(old, new, 1)
        try:
            path.write_text(mutated)
            purge_bytecode(path)
            went_green, line = run_test(node)
            went_red = not went_green
        finally:
            # A concurrent writer (another agent in this worktree, an editor's
            # autosave) would otherwise be silently CLOBBERED by the restore —
            # this harness would destroy work it never read. Detect it, preserve
            # it, and say so.
            if path.read_text() != mutated:
                conflict = path.with_suffix(path.suffix + ".retro-conflict")
                conflict.write_text(path.read_text())
                path.write_text(original)
                purge_bytecode(path)
                print(
                    f"\nCONCURRENT EDIT to {path} during mutation {i}. The "
                    f"foreign content was saved to {conflict} and the original "
                    f"restored. Re-run once the tree is quiet."
                )
                return 5
            path.write_text(original)
            purge_bytecode(path)
            assert sha(path) == original_sha, f"RESTORE FAILED for {path}"

        status = "RED (good)" if went_red else "STAYED GREEN"
        print(f"{i:>3}  {status:<12} {label}")
        print(f"     {'':<12} -> {node.split('::')[-1]}")
        print(f"     {'':<12}    {line}")
        if not went_red:
            decoration.append(f"{label} -> {node}")

    print("-" * 100)
    for path, (_, original_sha) in baseline.items():
        assert sha(path) == original_sha, f"tree not restored: {path}"
    print(f"tree restored byte-for-byte (sha256 verified on {len(files)} files)")

    ok, line = run_test(whole)
    print(f"AFTER     {len(TESTFILES)} gate files: {'GREEN' if ok else 'RED'}  |  {line}")
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
