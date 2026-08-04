"""The outcome grader must receive the conversation the agent actually had.

MEASURED 2026-08-04, from an independent audit that was then verified by hand
against the source.

`Runner::runToolUseLoop()` takes `array $conversation` BY VALUE — deliberately,
so each outcome iteration restarts from prompt + feedback. Its return type was
`{stop_reason, tokens_input, tokens_output, final_text}`. So every assistant
reply and every tool result the agent produced died with the local copy when
the method returned.

`runOutcomeLoop()` then built the grader's transcript with
`summariseConversation($conversation)` — the OUTER array, which never received
any of it. On iteration 0 the grader was handed literally the initial prompt
and nothing else.

The author knew the distinction: `array &$spans` two parameters later IS by
reference. And the Grader's own system prompt promises what never arrived —
"You CANNOT see the agent's reasoning, only the artifact + its conversation
transcript." The transcript was the missing half, so the outcome loop graded a
blank page and its verdicts meant nothing. Nothing pinned it.

SECOND DEFECT, same audit: `new Grader($llm)` reused the agent's own client,
with a trailing comment saying so — "grader uses the same LLM family". The
proposer graded its own work. Bone's loop engine states the opposite rule
outright ("The judge is code. The proposer is a model."), and this layer simply
did not follow it. `model.grader` in agent.yml now splits them; sharing is
still permitted but must be a per-agent choice rather than a property of the
code.

WHAT THIS GATE IS AND IS NOT. Wing has no PHP unit harness (only Playwright
e2e), so these are source-level assertions — weaker than executing the loop.
They pin the two specific wirings whose absence made the grader blind, and they
are retro-red against the tree before this commit. They cannot prove the grader
reasons well; only that it is shown the work.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "files/anatomy/wing/app/AgentKit/Runner.php"
AGENT = REPO / "files/anatomy/wing/app/AgentKit/Agent.php"
SCHEMA = REPO / "state/schema/agent.schema.yaml"


@pytest.fixture(scope="module")
def runner_src() -> str:
    assert RUNNER.is_file(), f"{RUNNER} is missing"
    return RUNNER.read_text(encoding="utf-8")


def _body(src: str, marker: str) -> str:
    """Source from a marker to the end — good enough to scope an assertion."""
    idx = src.index(marker)
    return src[idx:]


def test_the_tool_use_loop_returns_the_conversation(runner_src):
    """Without this the work is unreachable by anything downstream."""
    body = _body(runner_src, "private function runToolUseLoop")
    ret = body[body.index("return ["):body.index("return [") + 600]
    assert "'conversation'" in ret, (
        "runToolUseLoop no longer returns the conversation it built. Its "
        "`$conversation` parameter is BY VALUE, so if the array is not "
        "returned the agent's assistant and tool messages are discarded when "
        "the method exits — and the grader downstream sees only the prompt."
    )


def test_the_grader_transcript_is_built_from_the_loop_output(runner_src):
    """The defect itself, as the thing that must stay false."""
    m = re.search(r"\$transcript\s*=\s*\$this->summariseConversation\(([^;]+)\);",
                  runner_src)
    assert m, "the grader transcript is no longer built by summariseConversation"
    arg = m.group(1)
    assert "loopOut" in arg or "loop[" in arg, (
        f"the grader transcript is built from {arg.strip()!r}. That is the "
        f"OUTER conversation, which never receives the tool-use loop's inner "
        f"messages — on iteration 0 it is just the initial prompt. Build it "
        f"from what runToolUseLoop returned."
    )


def test_the_grader_client_is_not_unconditionally_the_agents_own(runner_src):
    """Judge and proposer must not share an identity by default of the code."""
    m = re.search(r"new Grader\(([^)]*)\)", runner_src)
    assert m, "the Grader is no longer constructed in Runner"
    arg = m.group(1).strip()
    assert arg != "$llm", (
        "`new Grader($llm)` hands the grader the very client that produced the "
        "work it is grading. Resolve a separate client when the agent declares "
        "`model.grader`, so sharing is a per-agent decision rather than a "
        "property of the code."
    )


def test_a_separate_grader_model_can_actually_be_declared(runner_src):
    """The split is useless if nothing can request it.

    Without this, `test_the_grader_client_is_not_unconditionally_the_agents_own`
    is satisfiable by any indirection that still always resolves to `$llm`.
    """
    assert "modelGraderUri" in AGENT.read_text(encoding="utf-8"), (
        "Agent has no modelGraderUri field, so no agent can ask for a separate "
        "grader and the split in Runner can never take effect"
    )
    assert "modelGraderUri" in runner_src, (
        "Runner never reads the agent's grader model"
    )
    schema = SCHEMA.read_text(encoding="utf-8")
    assert re.search(r"^\s+grader:\s*$", schema, re.MULTILINE), (
        "state/schema/agent.schema.yaml does not allow model.grader — the "
        "schema sets additionalProperties: false, so an agent.yml declaring it "
        "would be REJECTED at load time and the field is unreachable"
    )
