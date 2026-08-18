"""An iteration that runs out of calls must still produce its report.

MEASURED 2026-08-18 across every bound session the estate has ever run — the
same fourteen that `test_the_bound_agent_loop_is_unproven.py` counts. Reading
the `events` rows rather than the tally changes the diagnosis completely:

    agent_message  stop_reason=tool_use  "I need to walk the estate…"
    agent_tool_use ls
    agent_tool_result CLAUDE.md LICENSE README.md …
    agent_message  stop_reason=tool_use  ""
    agent_tool_use cat state/manifest.yml
    …  (twenty-five more, then the budget ends)

Nothing was malfunctioning. The model investigated competently and was still
investigating when the money ran out, because **nothing ever told it to stop
gathering and write**. The CLI path only looked better because its own harness
does this for us.

TWO DEFECTS, and the second is the expensive one:

1. `runToolUseLoop` offered tools on every call including the last, so the
   final turn was spent asking for one more file rather than answering.

2. When the `for` exhausted `MAX_LLM_CALLS_PER_ITERATION`, `$stopReason` was
   never reassigned — it kept its initialiser, `'end_turn'`, and returned
   alongside `final_text: ''`. A loop that gave up reported the stop reason
   that means *the model finished*. Downstream, the grader was handed an empty
   artifact and recorded `outcome_failed`, so the ledger blamed the agent for
   a report the runner had thrown away. This is the estate's own recurring
   defect exactly (`docs/hidden_fees/`, and the standing rule in CLAUDE.md):
   the success marker was written by the code that attempted the work.

The fix reserves the last call, withholds the tool schemas on it, and tells the
model plainly that the budget is spent. Withholding matters more than the
wording: asking for a summary while still offering tools reliably produces one
more tool call, because the instruction competes with the affordance and the
affordance wins.

WHAT THIS GATE DOES NOT DO. It reads source. It cannot prove a bound ceremony
now completes — only a session reaching a graded outcome can, and until one
does, `test_the_bound_agent_loop_is_unproven.py` stands and the agents stay
`unproven`. Retire BOTH files on the same good day, in the commit that shows
the session.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files/anatomy/wing/app/AgentKit/Runner.php"


def _src() -> str:
    return RUNNER.read_text(encoding="utf-8")


def test_the_runner_this_gate_describes_exists():
    """Positive control — a moved or renamed loop makes everything vacuous."""
    assert RUNNER.is_file(), "AgentKit/Runner.php is gone"
    src = _src()
    assert "private function runToolUseLoop(" in src, "the tool-use loop was renamed"
    assert "MAX_LLM_CALLS_PER_ITERATION" in src, "the per-iteration call cap is gone"


def test_the_exhaustion_path_does_not_claim_the_model_finished():
    """The initialiser IS the exhaustion path's return value — nothing assigns
    it when the `for` completes. So whatever it starts as is what a truncated
    run reports, and `end_turn` there is a lie with an empty artifact attached.
    """
    src = _src()
    loop_start = src.index("private function runToolUseLoop(")
    loop_src = src[loop_start:src.index("private function runOutcomeLoop(")]

    init = re.search(r"\$stopReason\s*=\s*'([a-z_]+)';", loop_src)
    assert init, "the tool-use loop no longer initialises $stopReason at all"
    assert init.group(1) != "end_turn", (
        "the tool-use loop initialises $stopReason to 'end_turn' again. Nothing "
        "reassigns it when the call cap is exhausted, so a run that was cut off "
        "mid-investigation reports that the model finished — and hands the "
        "grader an empty final_text to fail it for."
    )


def test_the_last_call_withholds_the_tools():
    """Wording alone does not bind. A model told to wrap up while tool schemas
    are still on the table will call a tool; removing the affordance is what
    leaves prose as the only available move."""
    src = _src()
    assert "SYNTHESIS_CALLS_RESERVED" in src, (
        "no calls are reserved for the wrap-up turn any more, so the iteration "
        "can once again spend its last call asking for another file."
    )
    assert re.search(r"\$isSynthesis\s*\?\s*\[\]\s*:", src), (
        "the synthesis turn no longer passes an EMPTY tool list to the model. "
        "Every adapter guards on `$tools !== []`, so passing [] is what removes "
        "the tools; passing them with a polite instruction does not."
    )


def test_a_reserved_call_leaves_a_working_budget():
    """The counterweight. Reserving zero restores the original defect;
    reserving most of the cap would starve the investigation to fix the
    reporting."""
    src = _src()
    reserved = re.search(r"SYNTHESIS_CALLS_RESERVED\s*=\s*(\d+)", src)
    cap = re.search(r"MAX_LLM_CALLS_PER_ITERATION\s*=\s*(\d+)", src)
    assert reserved and cap, "the two constants this balance depends on are gone"
    reserved_n, cap_n = int(reserved.group(1)), int(cap.group(1))
    assert reserved_n >= 1, "no call is reserved; the wrap-up turn cannot happen"
    assert reserved_n < cap_n / 2, (
        f"{reserved_n} of {cap_n} calls are reserved for wrapping up. The point "
        "is to end the investigation, not to replace it."
    )


def test_a_forced_ending_is_distinguishable_from_a_natural_one():
    """Both produce a report; only one had enough budget. If they collapse to
    the same stop reason, `agent_sessions` cannot answer 'should the cap go
    up' — and that question is the whole reason to record it."""
    src = _src()
    assert "call_cap_synthesis" in src, (
        "a report written on the forced final turn is no longer distinguished "
        "from one written by an agent that was actually done."
    )
    assert re.search(
        r"in_array\(\s*\$this->stopReason,\s*\[[^\]]*'call_cap_synthesis'",
        src,
        re.S,
    ), (
        "RunResult::isSuccessful() no longer counts call_cap_synthesis. The "
        "run produced the deliverable; failing it would make the exit code "
        "punish a spent budget and hide it among real crashes."
    )


def test_the_ceiling_also_gets_a_wrap_up_turn():
    """THE CORRECTION, made by running it (2026-08-18).

    The call-cap reservation above shipped in the morning. The first bound run
    under it died on the SESSION TOKEN CEILING at call 23 of 30 —
    260 745 in / 2 558 out — so the reserved 30th call was never reached and
    the run ended, once again, with nothing written. The reservation guarded a
    bound that does not bind.

    Both bounds must therefore end rather than stop, and the token one needs
    its own headroom: `assertSessionCeiling` measures the WORKING budget
    against `ceiling - SYNTHESIS_TOKEN_RESERVE`, and the wrap-up asks to be
    measured against the hard ceiling instead.
    """
    src = _src()
    assert "SYNTHESIS_TOKEN_RESERVE" in src, (
        "no tokens are held back from the session ceiling, so a run that hits "
        "it has nothing left to write a report with — the exact shape the "
        "first bound run demonstrated."
    )
    assert re.search(r"catch \(SessionCeilingReached [^)]*\)", src), (
        "the tool-use loop no longer catches SessionCeilingReached, so the "
        "ceiling once again ends the run mid-investigation with no report."
    )
    assert "ceiling_synthesis" in src, (
        "a report written after the ceiling fired is no longer distinguishable "
        "from a run that hit the ceiling and said nothing."
    )


def test_the_wrap_up_is_measured_against_the_hard_ceiling():
    """The counterweight, and the reason the reserve is not just a bigger
    ceiling: the wrap-up must be refused if IT cannot fit. A bound that can be
    talked past on the second attempt is not a bound."""
    src = _src()
    assert re.search(r"assertSessionCeiling\('synthesis',\s*false\)", src), (
        "the wrap-up no longer re-checks the HARD ceiling before spending. "
        "Without it the reserve becomes an extension anyone can claim, and the "
        "session's real bound moves by SYNTHESIS_TOKEN_RESERVE."
    )
    assert re.search(r"bool \$reserveHeadroom = true", src), (
        "assertSessionCeiling no longer distinguishes the working budget from "
        "the hard ceiling."
    )


def test_the_wrap_up_does_not_replay_the_transcript():
    """Why a plain 'one more call' cannot work: the conversation that reaches a
    ceiling is mostly tool RESULTS, resent every turn — 260 745 input tokens
    for 2 558 of output. Replaying it costs as much again, so the reserve would
    have to be a second ceiling."""
    src = _src()
    assert "compactForSynthesis" in src, (
        "the ceiling wrap-up no longer compacts the transcript, so it would "
        "replay a quarter-million tokens of tool output to ask one question."
    )
    body = src[src.index("private function compactForSynthesis"):]
    body = body[: body.index("\n\t/**", 10)] if "\n\t/**" in body[10:] else body
    assert "'text'" in body, "the compactor no longer keeps the model's own text"
    assert "tool_use" not in body and "tool_result" not in body, (
        "the compactor now carries tool blocks through. A tool_use whose result "
        "was dropped is an unanswered call, and several providers reject that "
        "shape outright."
    )


def test_a_failed_wrap_up_is_not_an_error():
    """It must not turn a bounded run into a crashed one: without the wrap-up
    the run ended at the ceiling with no report, which is exactly where a
    failure here leaves it."""
    src = _src()
    tail = src[src.index("private function synthesiseUnderCeiling"):]
    assert "catch (\\Throwable $exc)" in tail, (
        "the ceiling wrap-up no longer swallows its own failure, so a wrap-up "
        "that errors would crash a run that was merely out of budget."
    )
    assert "return '';" in tail, "a failed wrap-up must return no text, not throw"


def test_the_headroom_is_sized_from_what_calls_have_cost():
    """THE THIRD RESERVE, and the first that survived a run.

    Two were disproved by running them:
      * a flat 20 000 — at a tightened test ceiling of 30 000 it ate two thirds
        of the working budget;
      * 15% of the ceiling — the wrap-up was then REFUSED at `42 500 >= 40 000`,
        because the check happens BEFORE a call and the call it waves through
        costs whatever it costs. The budget was 34 000, the loop was under it,
        one call landed at 42 500, and the headroom had been spent by the very
        call it was meant to leave room after.

    So the reserve is sized from this session's own largest call. The
    conversation only grows, so the largest so far is the honest lower bound on
    the next one — and a reserve smaller than that cannot survive it.

    Under this version the first bound ceremony ever ran end to end:
    `status: idle`, `outcome_failed`, 6 707 output tokens, three iterations, a
    structured report that labelled its own gaps.
    """
    src = _src()
    assert "sessionLargestCall" in src, (
        "the headroom no longer tracks the largest call, so any fixed reserve "
        "can be consumed by the call that precedes the wrap-up."
    )
    assert re.search(r"\$this->sessionLargestCall\s*\+\s*self::SYNTHESIS_MIN_RESERVE", src), (
        "the reserve is no longer LARGEST CALL + floor. A reserve that does not "
        "cover the next call is spent before the wrap-up is reached."
    )
    assert re.search(r"\$this->sessionLargestCall = 0;", src), (
        "the largest-call counter is not reset per session, so one expensive "
        "run would shrink every later run's working budget in the same process."
    )


def test_an_iteration_boundary_stops_rather_than_discards():
    """The outcome loop's own ceiling check used to throw, and the throw
    travelled past everything the previous iteration had produced. Measured:
    `ceiling at iteration`, 13 502 in / 1 708 out, with a completed first
    iteration in hand. A budget that will not fund MORE work is not a reason to
    bin the work already done."""
    src = _src()
    loop = src[src.index("private function runOutcomeLoop("):]
    assert "assertSessionCeiling('iteration', false)" in loop, (
        "the iteration check no longer measures against the HARD ceiling. The "
        "reserved headroom belongs to the wrap-up inside runToolUseLoop; "
        "spending it here starves the thing it was reserved for."
    )
    assert "'max_iterations_reached'" in loop and "break;" in loop, (
        "the iteration-boundary ceiling no longer breaks out with the result so "
        "far — it throws again, discarding a completed iteration."
    )
    assert "if ($iteration === 0)" in loop, (
        "iteration 0 no longer rethrows. With nothing produced yet the ceiling "
        "IS the outcome, and reporting success over an empty run is the defect "
        "this whole file exists for."
    )
