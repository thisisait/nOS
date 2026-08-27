"""A format retry must name the actual fault.

MEASURED 2026-08-27, surveyor bound to MiniMax: the grader replied
{"result": "unsatisfied", "feedback": "..."} — well-formed JSON, one word
outside the closed enum. The retry told it "your previous reply was not
strict JSON" three times, so it kept fixing what it had got right, and the
run ended `outcome_failed` on a report that existed.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
GRADER = REPO / "files/anatomy/wing/app/AgentKit/Outcome/Grader.php"


def _retry_block() -> str:
    src = GRADER.read_text(encoding="utf-8")
    start = src.index("if ($attempt > 0)")
    return src[start: src.index("$response = $this->llm->send", start)]


def test_a_bad_enum_value_is_told_apart_from_bad_json():
    block = _retry_block()
    assert "not strict JSON" in block, "the malformed-JSON branch is gone"
    assert block.count("Message::userText") == 1 and "?" in block, (
        "the retry sends one unconditional message — a bad enum value and "
        "unparseable text get the same correction, and only one of them is true"
    )


def test_the_permitted_values_are_named_in_the_correction():
    block = _retry_block()
    for value in ("satisfied", "needs_revision", "failed"):
        assert value in block, (
            f"the correction never names '{value}', so a grader that guessed a "
            "synonym has nothing to correct itself against"
        )
