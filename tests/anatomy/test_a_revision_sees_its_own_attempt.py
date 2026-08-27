"""A needs_revision iteration must carry the attempt it is revising.

MEASURED 2026-08-27, surveyor bound to MiniMax: each iteration restarted from
prompt + feedback alone, so the agent re-explored from zero, hit the call cap
before writing, and the grader said "never produced a survey report" three
times — 261,767 in / 7,414 out, max_iterations_reached.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files/anatomy/wing/app/AgentKit/Runner.php"


def _revision_block() -> str:
    src = RUNNER.read_text(encoding="utf-8")
    i = src.index("GRADER FEEDBACK")
    return src[src.rindex("$conversation[] =", 0, i): src.index(");", i) + 2]


def test_the_attempt_travels_with_the_critique():
    block = _revision_block()
    assert "$finalText" in block, (
        "the revision message does not carry the previous attempt — the agent "
        "is asked to revise something it cannot see"
    )


def test_an_empty_attempt_is_named_rather_than_omitted():
    """Silence is the case that broke: no text and no mention of it reads as
    'nothing happened' rather than 'you never wrote the deliverable'."""
    block = _revision_block()
    assert re.search(r"\$finalText\s*!==\s*''", block), (
        "no branch for an empty previous attempt; the agent is handed a blank "
        "and learns nothing from it"
    )
