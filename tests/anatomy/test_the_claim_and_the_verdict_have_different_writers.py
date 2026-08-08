"""A roadmap row's claim and its verdict may not be written by one tool.

THE RULE, AND WHERE IT COMES FROM. `state/keap-tables/roadmap.table.yml` puts
`status` and `verified` side by side and argues the case in its own header:

    status    — what someone CLAIMS. Written by whoever files or does the work.
    verified  — what a PROBE OBSERVED. Written only by an independent check.
    […] A row whose `status` says done and whose `verified` says contradicted is
    the most useful row this table can hold, and it is unreachable in any design
    where one writer owns both.

That is not a style preference. It is the estate's most expensive recurring
defect written as a schema: `dispatched_at` stamped by the sender even when the
send failed; `status=scanned` written by a scan that never ran, whose fabricated
freshness the drift watcher then read; "Backup OK — N sources" over archives
that had been empty for weeks. Every one of them was a success marker written by
the code that attempted the work.

WHAT THIS GATE PINS. Two files, two jobs:

    tools/roadmap-update.py   moves the CLAIM. Cannot touch verified/evidence.
    tools/roadmap-verify.py   writes the VERDICT, and the verdict is the exit
                              code of a command it runs — never an argument.

A single file with two functions would satisfy the doctrine on the day it was
written and lose it in the first refactor. Two files make the boundary something
a test can see, which is the only kind of boundary that survives.

WHY IT READS THE AST. Both tools carry long headers that necessarily use the
words `status`, `verified`, `confirmed` and `contradicted` — that is what the
headers are about. A gate matching on text would fail them for explaining
themselves, which is how five gates in this repo were caught punishing correct
code in one week. So every assertion below is made against parsed syntax:
argparse flags, assignment targets, and the literal allow-list each tool filters
its write through. Prose is invisible to it.

WHAT IT CANNOT SEE. Whether the tools are actually USED, and whether a probe
passed to `--by` is a real check or `true`. A person can always verify nothing
carefully. This gate only guarantees that the two answers come from two writers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UPDATE = REPO / "tools/roadmap-update.py"
VERIFY = REPO / "tools/roadmap-verify.py"

VERDICT_COLUMNS = {"verified", "verified_by", "verified_at", "evidence"}
VERDICTS = {"confirmed", "contradicted"}


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def writable_set(path: Path) -> set[str]:
    """The module-level WRITABLE literal — the allow-list the write is filtered
    through. A tool without one is refused: an unfiltered write is a write whose
    reach nobody declared."""
    for node in tree(path).body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "WRITABLE" in names:
                return set(ast.literal_eval(node.value))
    pytest.fail(f"{path.name} declares no module-level WRITABLE allow-list — "
                "an unfiltered write cannot be gated")


def option_strings(path: Path) -> set[str]:
    """Every `--flag` passed to an add_argument call."""
    flags: set[str] = set()
    for node in ast.walk(tree(path)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    flags.add(arg.value.lstrip("-"))
    return flags


def literals_in_add_argument(path: Path) -> set[str]:
    """Every string literal anywhere inside an add_argument call, including
    `choices=` and `default=` — the two ways a flag could hand over a verdict
    without being named one."""
    found: set[str] = set()
    for node in ast.walk(tree(path)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.add(sub.value)
    return found


def args_attributes(path: Path) -> set[str]:
    """Every `args.<name>` read in the module."""
    return {
        node.attr
        for node in ast.walk(tree(path))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "args"
    }


def assignments_to(path: Path, target: str) -> list[ast.expr]:
    return [
        node.value
        for node in ast.walk(tree(path))
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == target for t in node.targets)
    ]


# ── both files exist, and they are two files ────────────────────────────────

def test_both_writers_exist():
    missing = [p.name for p in (UPDATE, VERIFY) if not p.exists()]
    assert not missing, (
        "the claim and the verdict need separate writers; missing: "
        + ", ".join(missing))


# ── the claim writer may not certify its own claim ──────────────────────────

def test_the_claim_writer_cannot_write_a_verdict():
    reach = writable_set(UPDATE)
    leaked = sorted(reach & VERDICT_COLUMNS)
    assert not leaked, (
        f"tools/roadmap-update.py may write {leaked} — that is the verdict, and "
        "a writer that can certify its own claim will eventually be asked to. "
        "Move it to tools/roadmap-verify.py.")


def test_the_claim_writer_offers_no_verdict_flag():
    offered = sorted(option_strings(UPDATE) & (VERDICT_COLUMNS | VERDICTS))
    assert not offered, (
        f"tools/roadmap-update.py takes {offered} on the command line — the "
        "verdict must come from a probe, not from whoever is claiming.")


# ── the verdict writer may not move the claim ───────────────────────────────

def test_the_verdict_writer_cannot_move_the_claim():
    reach = writable_set(VERIFY)
    assert "status" not in reach, (
        "tools/roadmap-verify.py may write `status` — then one tool decides both "
        "what is claimed and whether it is true, which is the design the two "
        "columns exist to prevent.")


def test_the_verdict_writer_takes_no_status_argument():
    assert "status" not in option_strings(VERIFY), (
        "tools/roadmap-verify.py declares a --status flag")
    assert "status" not in args_attributes(VERIFY), (
        "tools/roadmap-verify.py reads args.status — the status it sends must "
        "come from the row it read, so the write validates, and from nowhere else")


# ── the verdict is produced, never supplied ─────────────────────────────────

def test_no_flag_can_hand_over_a_verdict():
    """Not just `--verdict`: a `choices=` or `default=` carrying `confirmed`
    would smuggle the same thing past a name check."""
    smuggled = sorted(literals_in_add_argument(VERIFY) & VERDICTS)
    assert not smuggled, (
        f"tools/roadmap-verify.py accepts {smuggled} through an argparse flag. "
        "The verdict must be the exit code of the command the tool runs — if it "
        "can be passed in, this file becomes a second way to make a claim.")


def test_the_verdict_is_never_read_from_the_arguments():
    for value in assignments_to(VERIFY, "verdict"):
        reads = {
            sub.attr for sub in ast.walk(value)
            if isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name) and sub.value.id == "args"
        }
        assert not reads, (
            f"`verdict` is assigned from args.{'/args.'.join(sorted(reads))} — "
            "it must be derived from the probe's exit code. (`--unverifiable` is "
            "allowed to say NO probe exists, which is why it supplies a reason "
            "and not a verdict.)")


def test_unverifiable_is_reachable_so_the_other_two_stay_honest():
    """A tool with only pass/fail pushes every unprobeable row into one of them.
    The third answer is what keeps `confirmed` meaning something."""
    src = VERIFY.read_text(encoding="utf-8")
    assert "unverifiable" in option_strings(VERIFY) or "unverifiable" in src, (
        "tools/roadmap-verify.py has no way to record that no probe exists; "
        "rows nobody can check will silently inherit a verdict they did not earn")
