"""A session must be bounded, not just its iterations.

MEASURED 2026-08-16, reading Runner before the ceilings existed. Three caps,
all PER ITERATION, and they multiply:

    600s per SDK request  ×  30 calls/iteration  ×  10 iterations  ≈  15 hours

for a single stuck agent — and nothing counted tokens at all. The design doc
the agentic loop hangs on (`docs/idea/11-agentic-loop.md` §5) is titled
"Bounded, because unbounded is the failure mode"; the SESSION was the level
with no bound, which is the level the operator pays for.

WHAT IS PINNED HERE:

  * both ceilings exist and are read from env with a constant fallback, so a
    supervised night can be tightened without editing code;
  * they are checked BEFORE the spend. A ceiling enforced after the call has
    already been made is a receipt, not a limit;
  * the refusal is its own exception type. `LLMTransientError` would be
    retried and `LLMPermanentError` would fall back to the secondary model —
    both spend MORE, which is precisely what a ceiling exists to prevent, so
    inheriting from either would be the defect wearing the fix's name;
  * the clock is also checked at the iteration boundary, because the Grader
    holds its OWN client and its tokens are invisible to the counter. A bound
    believed wider than it is would be worse than no bound.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTKIT = REPO / "files/anatomy/wing/app/AgentKit"
RUNNER = AGENTKIT / "Runner.php"
EXC = AGENTKIT / "SessionCeilingReached.php"


def _runner() -> str:
    return RUNNER.read_text(encoding="utf-8")


def test_both_ceilings_exist_and_are_operator_tunable():
    src = _runner()
    for const, env in (
        ("SESSION_WALL_CLOCK_S", "NOS_AGENT_SESSION_WALL_CLOCK_S"),
        ("SESSION_TOKEN_CEILING", "NOS_AGENT_SESSION_TOKEN_CEILING"),
    ):
        assert f"const {const}" in src, f"the {const} ceiling is gone"
        assert env in src, (
            f"{const} is no longer env-overridable ({env}). A supervised night "
            "must be able to tighten a backstop without a code change."
        )


def test_the_ceiling_is_checked_before_the_call_not_after():
    """Order is the whole property. After the call it is a receipt."""
    src = _runner()
    check = src.index("$this->assertSessionCeiling('llm_call')")
    call = src.index("$this->callWithRetry(", check - 400)
    assert check < call, (
        "the session-ceiling check no longer precedes callWithRetry. A limit "
        "consulted after the spend cannot prevent it."
    )


def test_the_clock_also_bounds_the_iteration_loop():
    """The Grader's tokens are invisible to the counter; the clock is what
    reaches them."""
    src = _runner()
    assert "$this->assertSessionCeiling('iteration')" in src, (
        "the iteration loop no longer checks the ceiling, so a session whose "
        "spend is mostly in the grader has no bound at all."
    )


def test_the_refusal_is_not_an_llm_error():
    assert EXC.is_file(), "SessionCeilingReached is gone"
    src = EXC.read_text(encoding="utf-8")
    assert re.search(r"extends\s+\\?RuntimeException", src), (
        "SessionCeilingReached no longer extends RuntimeException. If it "
        "became an LLM error it would be RETRIED (transient) or FALLEN BACK "
        "(permanent) — both spend more, which is what the ceiling prevents."
    )
    # THE DECLARATION, not the prose. A first draft asserted the two LLM error
    # names were absent from the FILE, and went red on the exception's own
    # docstring explaining why it must not be one of them — a gate reading the
    # reasoning about the fix as the defect.
    declaration = re.search(r"^\s*(?:final\s+)?class\s+\w+[^\n{]*", src, re.M)
    assert declaration, "no class declaration found in SessionCeilingReached.php"
    assert "LLMError" not in declaration.group(0), declaration.group(0)
    for llm_error in ("LLMTransientError", "LLMPermanentError", "LLMCapabilityError"):
        assert llm_error not in declaration.group(0), (
            f"SessionCeilingReached now extends {llm_error}: it would be "
            "retried or fallen back, and both spend more than stopping."
        )


def test_the_counters_are_reset_per_run():
    """Instance state that survives a run would bound the SECOND session by
    the first one's spend — a ceiling that tightens itself silently."""
    src = _runner()
    body = src[src.index("public function run("):]
    body = body[: body.index("\n\tprivate function ")]
    assert "$this->sessionTokens = 0;" in body, "the token counter is not reset per run"
    assert "$this->sessionDeadline = microtime(true)" in body, (
        "the deadline is not recomputed per run"
    )
