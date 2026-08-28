"""A format retry must name the actual fault — and must not re-open content.

MEASURED 2026-08-27, surveyor bound to MiniMax: the grader replied
{"result": "unsatisfied", "feedback": "..."} — well-formed JSON, one word
outside the closed enum. The retry told it "your previous reply was not
strict JSON" three times, so it kept fixing what it had got right, and the
run ended `outcome_failed` on a report that existed.

REWRITTEN 2026-08-29 for the Q9 three-stage contract, which closes the same
defect one level up. There is no longer a retry LOOP to inspect: shape faults
go to a deterministic parser, then to ONE format-only re-ask, then to
UNPARSEABLE, and a bad enum — a CONTENT fault — is never re-asked at all,
because a second answer is free to differ from the first. The 2026-08-27
lesson survives as the assertion that a bad enum does not discard the
critique the grader got right.

This is a source-level gate; the parser's behaviour is exercised for real in
test_a_repaired_output_says_so.py.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
GRADER = REPO / "files/anatomy/wing/app/AgentKit/Outcome/Grader.php"


def _src() -> str:
    return GRADER.read_text(encoding="utf-8")


def test_shape_faults_go_through_the_three_stage_contract():
    src = _src()
    assert "OutputRepair::parse" in src, (
        "the grader parses model JSON on its own again — the deterministic "
        "shape repair and the single bounded re-ask are bypassed"
    )
    assert "$this->llm->send" in src


def test_there_is_exactly_one_reask_and_it_reformats_only():
    """Two calls in the whole method: the grade, and at most one reformat.

    A loop here is what let a format correction quietly become a re-grade.
    """
    src = _src()
    assert src.count("$this->llm->send") == 2, (
        "the grader makes more than one possible retry call — the format "
        "re-ask is bounded to ONE by the Q9 contract"
    )
    reask = src[src.index("OutputRepair::parse"):src.index("$repaired =")]
    assert "You do not evaluate" in reask, (
        "the re-ask does not forbid evaluation, so the reformat is free to "
        "reconsider the verdict while it is in there"
    )
    assert "SAME" in reask, "the re-ask does not quote the original content back"


def test_a_bad_enum_value_is_not_treated_as_a_shape_fault():
    src = _src()
    branch = src[src.index("in_array($result, [self::RESULT_SATISFIED"):]
    branch = branch[: branch.index("return [") + 400]
    assert "OutputRepair" not in branch and "llm->send" not in branch, (
        "a value outside the enum triggers another model call. It is a "
        "CONTENT fault: the answer is well-formed and wrong, and re-asking "
        "invites a different verdict rather than the same one reformatted."
    )


def test_a_bad_enum_does_not_discard_the_critique():
    """The 2026-08-27 defect itself: one word outside the enum threw away a
    whole correct critique."""
    src = _src()
    branch = src[src.index("in_array($result, [self::RESULT_SATISFIED"):]
    branch = branch[: branch.index("];", branch.index("return ["))]
    assert "$decoded['feedback']" in branch, (
        "the bad-enum branch returns no feedback from the grader's own reply — "
        "the critique it got right is dropped for the word it got wrong"
    )


def test_the_permitted_values_are_named_where_the_grader_can_see_them():
    src = _src()
    system = src[src.index("SYSTEM_TEMPLATE = "):src.index("public function __construct")]
    for value in ("satisfied", "needs_revision", "failed"):
        assert value in system, (
            f"the system prompt never names '{value}', so a grader that guessed "
            "a synonym has nothing to correct itself against"
        )
