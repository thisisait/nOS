"""The vacuity check the roadmap asks for cannot exist in the form it names.

THE FINDING IS REAL. `wordpress_version: 9.9.9-nonexistent` passes the `repo`
gate set 3868/0. The set is ansible-lint + genome-codegen + pytest-anatomy and
not one of them reads a version VALUE, so for that proposal `pass` carried no
information about the change. Three of four merged diffs were version bumps.

THE FIX THE ROW NAMES DOES NOT. `loop-verdict-vacuity` says: *"when no judge has
an oracle_paths overlap with the diff, record `nothing objected`, not `pass`."*
Measured 2026-08-29, and this file is that measurement kept runnable:
`oracle_paths` are the paths that ARE a judge's oracle, and `budget_for()`
turns every one of them into a FORBIDDEN rule for any proposal judged by a set
containing that judge (`budget.py`, docs/idea/11-agentic-loop-contract.md §5.1).
So for any proposal that exists the overlap is empty — not usually, but by construction, because a proposal that
overlapped one was refused before it got a uuid. A check on that overlap has no
state in which it can distinguish an informative pass from a vacuous one; it
would report every verdict as vacuous, or, inverted, none.

WHAT WOULD ACTUALLY MEASURE IT is not a path test at all. Whether a judge's
assertions depend on a changed value is undecidable in general, and the one
proposal class where it is decidable — does this pin resolve upstream? — needs a
judge that reads the value. That judge was proposed and REFUSED
(`loop-pin-resolves-refused`, dropped: it is a network read, so it is not
deterministic and cannot be an oracle). The two rows have to be settled
together; closing this one alone can only produce a check that agrees with
whatever it is asked.

This file exists so the row cannot be implemented blind. It fails if the premise
it rests on ever stops holding — if an oracle path becomes reachable by a
proposal, the overlap check becomes possible and this note is stale.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/bone"))

judges = pytest.importorskip("judges")
budget = pytest.importorskip("budget")


def _registry():
    return judges.load_registry(str(REPO))


def test_every_oracle_path_is_forbidden_to_the_proposals_it_would_judge() -> None:
    """The premise, stated as a property of every gate set rather than a claim.

    If this passes, an "oracle_paths overlap with the diff" is empty for every
    proposal that can exist — which is what makes the proposed vacuity check
    unimplementable.
    """
    reg = _registry()
    for name, spec in reg.gate_sets.items():
        b = budget.budget_for(name, registry=reg, repo_root=str(REPO))
        forbidden = {r.pattern for r in b.forbidden}
        for judge_name in spec.judges:
            for oracle in reg.judges[judge_name].oracle_paths:
                assert oracle in forbidden, (
                    f"gate set {name!r}: judge {judge_name!r} declares oracle "
                    f"{oracle!r} which the budget does NOT forbid. The vacuity "
                    "check in `loop-verdict-vacuity` becomes implementable the "
                    "day this stops holding — re-read that row rather than "
                    "deleting this test."
                )


def test_a_touchable_path_overlaps_no_oracle() -> None:
    """The other direction, on the paths real proposals actually touch.

    A version bump — the class the finding was measured on — overlaps nothing,
    so the proposed check would call it vacuous. So would every other allowed
    diff, which is the whole objection: a signal that never varies is not one.
    """
    reg = _registry()
    b = budget.budget_for("repo", registry=reg, repo_root=str(REPO))
    oracles = {r.pattern for r in b.forbidden}
    for path in ("roles/pazny.wordpress/defaults/main.yml",
                 "files/anatomy/plugins/n8n-base/plugin.yml",
                 "docs/llm/security/remediation-queue.json"):
        assert path not in oracles, f"{path} is now an oracle path; see above"


def test_the_finding_itself_is_not_being_dismissed() -> None:
    """Reading this file as "nothing to do here" would be the wrong lesson.

    The measurement that started it stands: no judge in `repo` reads a version
    value. This asserts that none of the three has become one behind our backs —
    if a judge appears whose argv resolves a pin, the finding is closed by the
    judge, not by a path test, and this file should go with it.
    """
    reg = _registry()
    argvs = " ".join(" ".join(reg.judges[j].argv) for j in reg.gate_sets["repo"].judges)
    assert "resolve" not in argvs and "pin" not in argvs, (
        "a judge in `repo` now looks like it resolves pins. If a value-reading "
        "oracle has landed, loop-verdict-vacuity is closed by it — settle that "
        "row and delete this file rather than keeping a note about a gap that "
        "was filled."
    )
