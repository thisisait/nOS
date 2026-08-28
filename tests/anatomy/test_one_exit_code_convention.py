"""An exit code says what happened to the PROCESS. It is not a place for a count.

THE ESTATE HAD THREE CONVENTIONS, and two of them shared integers:

  * Pulse's subprocess runner reserves 126 (allowlist refusal), 127 (command
    not found) and -9 (SIGKILL after timeout). These are facts about whether
    the process ran at all.
  * `state/judge-sets.yml` declares `pass_exit` / `fail_exit` per judge,
    because tools disagree — ansible-lint fails with 2, genome-codegen with 1 —
    and anything outside both lists is INDETERMINATE rather than guessed at.
  * `tools/nos-smoke.py` returned THE NUMBER OF FAILED PROBES, capped at 127.

The third collided with the first. A smoke run with 127 dead probes and a
binary that never started produced the same integer, and a caller could not
tell "the estate is entirely down" from "python3 is missing". The cap was not a
safety measure, it was the collision.

FIXED 2026-08-06 by making the smoke answer 0 or 1 and reading the count from
stdout, where `work_regex` already read it. Nothing lost: `tasks/post-smoke.yml`
compared `rc != 0` and never looked at the magnitude, and the judge adapter
moved from `exit_count` to the `exit_zero` vocabulary every other judge uses.

The rule this file holds: a magnitude belongs in output, an outcome belongs in
the exit code, and the two must not be the same integer.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "tools/nos-smoke.py"
REGISTRY = REPO / "state/judge-sets.yml"
RUNNER = REPO / "files/anatomy/pulse/pulse/runners/subprocess.py"

#: Codes the Pulse runner reserves for facts about the PROCESS. No tool may
#: return one of these to mean something about its own findings.
RESERVED = {126, 127, -9}


def test_the_smoke_returns_an_outcome_not_a_count():
    tree = ast.parse(SMOKE.read_text(encoding="utf-8"))
    main = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main is not None, "nos-smoke has no main() — this gate is blind"

    returns = [n for n in ast.walk(main) if isinstance(n, ast.Return) and n.value is not None]
    assert returns, "main() returns nothing"
    for node in returns:
        # `return min(failed, 127)` is the shape that was wrong: a call whose
        # value is derived from a count rather than from a verdict.
        if isinstance(node.value, ast.Call):
            fname = getattr(node.value.func, "id", "")
            assert fname != "min", (
                f"nos-smoke:{node.lineno} returns min(...) — the failure count is "
                f"back in the exit code, where it collides with the runner's "
                f"reserved {sorted(RESERVED)}"
            )
        for const in ast.walk(node):
            if isinstance(const, ast.Constant) and isinstance(const.value, int):
                assert const.value in (0, 1), (
                    f"nos-smoke:{node.lineno} can return {const.value}. The exit "
                    f"code is an outcome (0 or 1); a magnitude goes to stdout, "
                    f"which is where work_regex reads it."
                )


def test_the_smoke_judge_speaks_the_shared_vocabulary():
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    smoke = registry["judges"]["nos-smoke"]
    assert smoke["adapter"] == "exit_zero", (
        f"nos-smoke's judge adapter is {smoke['adapter']!r}; `exit_count` reads "
        f"the exit status as a magnitude, which is the convention this removed"
    )
    assert smoke.get("pass_exit") == [0] and smoke.get("fail_exit") == [1], (
        "the smoke judge must declare its codes explicitly like every other "
        "judge here — a naive `!= 0` is right by accident and wrong on the day "
        "the tool adds a second failure code"
    )
    # The count did not vanish, it moved. If work_regex went with it, the
    # judge would have no ratchet and a zero-probe run would read as a pass.
    assert smoke.get("work_regex"), "nos-smoke lost the stdout work count"


def test_the_reserved_process_codes_are_still_reserved():
    """Positive control: the runner's meanings are what make the collision real."""
    source = RUNNER.read_text(encoding="utf-8")
    for code in (126, 127):
        assert f"exit_code={code}" in source, (
            f"the Pulse runner no longer returns {code}; if its reserved codes "
            f"changed, the rule above needs re-deriving rather than assuming"
        )


def test_no_pulse_job_claims_a_reserved_code_as_a_finding():
    """A job may declare "this code means I found something" — but not for a
    code that means "you never ran me"."""
    offenders = []
    for pattern in ("files/anatomy/plugins/*/plugin.yml", "files/anatomy/agents/*/agent.yml"):
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict):
                continue
            for job in (doc.get("pulse") or {}).get("jobs") or []:
                for code in (job.get("findings_exit_codes") or []):
                    if code in RESERVED:
                        offenders.append(f"{path.name}:{job.get('name')} claims {code}")
    assert not offenders, (
        "a job declares a reserved process code as a findings code, so a run "
        "that never started would read as a successful scan:\n  "
        + "\n  ".join(offenders)
    )


def test_the_stale_comment_was_corrected():
    """The registry described the old contract in prose directly above the new
    one. A comment that contradicts the line under it is the defect this repo
    keeps finding, and leaving it here would have been a fresh instance."""
    text = REGISTRY.read_text(encoding="utf-8")
    block = text[text.find("# ── nos-smoke"):text.find("# ── cortex-corpus-diff")]
    assert not re.search(r"^\s*# Exit IS the failure count", block, re.M), (
        "judge-sets.yml still asserts the smoke's exit is a count"
    )
