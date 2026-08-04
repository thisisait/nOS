"""Every fan-out in a workflow must say why it is a fan-out.

MEASURED 2026-08-04, from this session's own subagent transcripts:

    tool calls                1 366
    duplicate calls              76   (7%)
    output tokens           710 455          10% of billable equivalent
    cache creation        9 390 136          33%
    cache read          197 827 381          57%
    duration  median 436s  max 996s   -> a barrier waits 2.3x the median

Roughly 90% of the spend is CONTEXT and 10% is product. So the expensive part of
an agent is not the work it repeats — duplicate calls were 7% — it is the
orientation tax each one pays before producing anything. In a fan-out where N
alternatives are produced and one is kept, that tax is paid N times for one
answer, and the barrier additionally waits for the slowest.

The operator's rule, which this gate enforces: fan out only when the task is
unambiguous, in a different directory, with no dependency on another agent's
work. Two shapes qualify —

  union  each agent searches a DISJOINT space; outputs are added together
  veto   N independent attempts to REFUTE one claim; disagreement is the product

— and `selection` (N alternatives, keep one) is banned without an explicit
written justification, because quality there scales as max() while cost scales
as sum().

WHAT THIS GATE CAN AND CANNOT DO. It cannot decide whether a fan-out is really
disjoint; that is a judgement. What it can do is refuse an UNDECLARED one, which
is the state every fan-out starts in and the state the three anatomy-view
workflows were in when first written — their Build phase ran three parallel
agents to write a BFF route, a shell and a view, where the view could not be
written without the other two. A chain wearing a fan-out's clothes.

Retro-red: run against those files as first authored and the Build phase fails.

Doctrine: docs/doctrine/workflows.md (detail: docs/workflow-standard.md)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".claude/workflows"
DOCTRINE = REPO / "docs/doctrine/workflows.md"

# A declaration is a comment naming the semantics, within reach of the call.
LEGAL_KINDS = ("union", "veto")
LOOKBACK_LINES = 14
# The call body a fan-out spans; a `phase:` marker often sits INSIDE it.
LOOKAHEAD_LINES = 30


def _workflow_files() -> list[Path]:
    if not WORKFLOWS.is_dir():
        return []
    return sorted(WORKFLOWS.glob("*.js"))


def _fanouts(path: Path):
    """Yield (lineno, preceding_block, call_body) for each parallel() call.

    The call BODY matters as much as the preamble, and finding that out cost a
    mutation test: the build-phase check below originally scanned only the lines
    ABOVE a call, so a fan-out whose `{ phase: 'Build' }` sat on the line BELOW
    it sailed straight through. The mutation was caught — but by the
    declaration check, not by the one that claimed to catch it. A check you
    cannot demonstrate firing is decoration, so it now reads both sides.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "parallel(" not in line:
            continue
        # Skip prose: a mention inside a template literal or a comment is not a call.
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        if not re.search(r"\bparallel\s*\(", line):
            continue
        start = max(0, i - LOOKBACK_LINES)
        yield (i + 1,
               "\n".join(lines[start:i]),
               "\n".join(lines[i:i + LOOKAHEAD_LINES]))


def test_the_doctrine_this_gate_enforces_exists():
    """A gate whose rule lives only in the gate is a rule nobody can read."""
    assert DOCTRINE.is_file(), (
        "docs/doctrine/workflows.md is gone — this gate enforces a rule "
        "that no longer has a written form, which makes it folklore"
    )
    text = DOCTRINE.read_text(encoding="utf-8")
    for kind in LEGAL_KINDS:
        assert kind in text, f"the doctrine no longer defines '{kind}'"


def test_workflow_definitions_are_tracked():
    """Untracked workflows cannot be proposed against, or judged.

    This is the recursion prerequisite from the doctrine's §8, and it is
    checkable: .gitignore must un-ignore the directory.
    """
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "!.claude/workflows/" in gitignore, (
        "workflow definitions are gitignored. A recursive loop cannot propose a "
        "change to a file that is not in the repository, and a judge cannot be "
        "retro-red against a version that was never committed."
    )


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_fanout_declares_its_semantics(path):
    """The defect, as the thing that must stay false."""
    undeclared = []
    for lineno, preceding, _body in _fanouts(path):
        low = preceding.lower()
        if any(k in low for k in LEGAL_KINDS):
            continue
        # An explicit, written justification also passes — the rule is that a
        # fan-out must be ARGUED, not that one word must appear.
        if "selection" in low and "justif" in low:
            continue
        undeclared.append(lineno)

    assert not undeclared, (
        f"{path.name} fans out at line(s) {undeclared} without saying which "
        f"kind it is. Legal kinds: {' | '.join(LEGAL_KINDS)}. If neither fits, "
        f"it is probably a CHAIN — step B needing step A's output — and running "
        f"a chain in parallel is a guess followed by a rewrite. Measured "
        f"2026-08-04: 90% of multi-agent spend is context, so every extra agent "
        f"whose output you discard or must reconcile is paid for in full. "
        f"See docs/doctrine/workflows.md §1."
    )


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_a_build_phase_is_not_a_fanout(path):
    """The specific mistake this gate was born from.

    Construction steps — a route, a shell, a component — form a chain: each
    needs the previous one's real shape. A fan-out there does not parallelise
    the work, it parallelises the GUESSING, and the reconciliation costs more
    than the wall-clock saved.

    Checked narrowly: a parallel() whose nearby labels look like build steps.
    """
    offenders = []
    for lineno, preceding, body in _fanouts(path):
        window = (preceding + "\n" + body).lower()
        # Only complain when this fan-out is plainly the build phase — the
        # marker may sit above the call OR inside its body.
        if "phase: 'build'" in window or 'phase: "build"' in window \
           or 'phase("build")' in window or "phase('build')" in window:
            offenders.append(lineno)

    assert not offenders, (
        f"{path.name} runs its BUILD phase as a fan-out at line(s) {offenders}. "
        f"A build step needs the previous step's real contract — route paths, "
        f"response shape, mount seam. Run them sequentially and pass each "
        f"result into the next prompt."
    )


def test_the_gate_has_something_to_check():
    """Positive control.

    Every assertion above is vacuously satisfied by an empty directory. If the
    workflows move, this gate must move with them rather than quietly passing.
    """
    assert _workflow_files(), (
        "no workflow definitions found under .claude/workflows/ — either they "
        "moved (update this gate) or they stopped being tracked (see "
        "test_workflow_definitions_are_tracked)"
    )
