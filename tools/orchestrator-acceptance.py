#!/usr/bin/env python3
"""The four-item acceptance test every candidate orchestration host must pass.

    tools/orchestrator-acceptance.py --host null        # the reference pair
    tools/orchestrator-acceptance.py --host langgraph   # the spike's subject
    tools/orchestrator-acceptance.py --list

WRITTEN BEFORE THE SPIKE, deliberately — `docs/idea/17-loop-split-refactor-graph.md`
clause 2 requires it, because a spike that writes its own pass mark grades
itself. Nothing in this file knows what LangGraph is.

WHAT IS BEING TESTED, and why these four. AgentKit's governance is not spread
across its 52 catalogued behaviours; it hangs off a very small number of load-
bearing points, and doc 17 measured which:

  1. ABORT BEFORE A MODEL CALL — `Runner.php:495`, `assertSessionCeiling`
     ahead of every send. A host that can only observe a call it is about to
     make cannot enforce a ceiling; it can only report having exceeded one.

  2. ABORT AT AN ITERATION BOUNDARY — `Runner.php:681`, the top of every
     outcome iteration. Distinct from (1): a host may gate the model and
     still have no seam between turns.

  3. THE MODEL'S EXCEPTION PROPAGATES — enforced in AgentKit by catch
     ORDERING (`:815` above `:828`), so `LLMCapabilityError` escapes rather
     than being absorbed. A framework whose retry or model-fallback swallows
     it will, on this estate, answer from a backend the agent's own Article-30
     record does not name. Silence here is the residency claim quietly
     becoming false.

  4. AN ABORT STILL RECORDS THE SPEND — HARD FAIL. Commit `0c84b92b` ("a
     ceiling is not an error") exists because a run that stops must still say
     what it cost; a host that discards the tally on an aborted run makes
     every budget in the estate an estimate.

Item 4 is the only hard fail. Items 1-3 are discriminators; six of eleven
surveyed hosts pass them, which is exactly why they are not sufficient alone.

THE FAKE MODEL SPENDS NOTHING. No network, no key, no provider. A host that
cannot be driven with a stub model is not a candidate for this estate anyway.

ADDING A CANDIDATE: implement `Host` (four methods), register it in HOSTS.
The harness never imports a candidate that is not asked for, so a missing
dependency is a skip for that host and not a failure of the run.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ---------------------------------------------------------------------------
# the stub model — the only thing every probe agrees about
# ---------------------------------------------------------------------------

class Refusal(Exception):
    """Raised by a policy callback to stop a run. A host passes item 1 or 2
    by making this reach the caller INSTEAD of a model call, not after one."""


class ModelBroke(Exception):
    """The model's own failure. Item 3 asks whether this exact instance
    arrives at the caller — not an instance of the same class, and not a
    wrapper carrying its message."""


@dataclass
class FakeModel:
    """Counts what a host actually does, rather than what it reports doing.

    `calls` is the load-bearing number in three of the four probes: a host
    that aborts a call it has already made scores zero on item 1, and a host
    that quietly retries a permanent error scores zero on item 3.
    """

    scripted: list[str] = field(default_factory=lambda: ["one", "two", "three", "four"])
    raises_on_call: int | None = None      # 1-indexed call that throws
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def send(self, prompt: str) -> str:
        self.calls += 1
        if self.raises_on_call is not None and self.calls == self.raises_on_call:
            # Spend IS recorded before the throw: a failed call still cost
            # its input tokens, and a host that only tallies on success will
            # under-report every outage.
            self.tokens_in += 10
            raise ModelBroke(f"provider refused on call {self.calls}")
        self.tokens_in += 10
        self.tokens_out += 5
        index = min(self.calls - 1, len(self.scripted) - 1)
        return self.scripted[index]


@dataclass
class Ledger:
    """What the host claims was spent. Item 4 compares it against the model's
    own count, so a host cannot pass by reporting a plausible number."""

    tokens_in: int = 0
    tokens_out: int = 0
    finished: bool = False
    stop_reason: str | None = None


@dataclass
class Run:
    """What a host returns. `raised` carries the exception that escaped, if
    any — `None` means the run ended without one."""

    ledger: Ledger
    raised: BaseException | None = None


class Host(Protocol):
    """A candidate orchestration host, reduced to what the estate needs of it.

    Every method drives ONE agent run to completion or refusal. `before_call`
    and `before_iteration` are policy callbacks: raising `Refusal` inside them
    must stop the run. The host may translate `Refusal` into its own control
    flow, but `Run.raised` must then carry something the caller can recognise
    as a refusal rather than a success.
    """

    name: str

    def available(self) -> str | None:
        """None if usable; otherwise a one-line reason to skip."""

    def run(
        self,
        model: FakeModel,
        max_iterations: int,
        before_call: Callable[[int], None] | None = None,
        before_iteration: Callable[[int], None] | None = None,
    ) -> Run:
        """Drive the loop. Both callbacks receive a 1-indexed counter."""


# ---------------------------------------------------------------------------
# the reference host — the harness's own positive control
# ---------------------------------------------------------------------------

class NullHost:
    """A minimal loop that passes all four items by construction.

    It exists so a failing candidate can be distinguished from a broken
    harness. If `--host null` ever fails, the probe is wrong and the
    candidate's result means nothing.
    """

    name = "null"

    def available(self) -> str | None:
        return None

    def run(self, model, max_iterations, before_call=None, before_iteration=None) -> Run:
        ledger = Ledger()
        raised: BaseException | None = None
        try:
            for turn in range(1, max_iterations + 1):
                if before_iteration is not None:
                    before_iteration(turn)
                if before_call is not None:
                    before_call(turn)
                model.send(f"turn {turn}")
        except BaseException as exc:            # noqa: BLE001 — the point is to see everything
            raised = exc
        finally:
            # The tally is written in `finally` ON PURPOSE. This is item 4:
            # the spend is recorded on the way out whether the way out was a
            # return, a refusal or the model breaking.
            ledger.tokens_in = model.tokens_in
            ledger.tokens_out = model.tokens_out
            ledger.finished = True
            ledger.stop_reason = type(raised).__name__ if raised else "completed"
        return Run(ledger=ledger, raised=raised)


class BrokenHost(NullHost):
    """A host that fails every item, so `--host broken` proves each probe can
    fail. A probe that no host has ever failed is a probe nobody has tested."""

    name = "broken"

    def run(self, model, max_iterations, before_call=None, before_iteration=None) -> Run:
        ledger = Ledger()
        raised = None
        for turn in range(1, max_iterations + 1):
            try:
                model.send(f"turn {turn}")          # calls FIRST — item 1 lost
                if before_call is not None:
                    before_call(turn)
                if before_iteration is not None:
                    before_iteration(turn)
            except ModelBroke:
                continue                            # swallowed — item 3 lost
            except Refusal as exc:
                raised = exc
                break
        # ledger left at zero — item 4 lost
        return Run(ledger=ledger, raised=raised)


# ---------------------------------------------------------------------------
# the four probes
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    item: int
    title: str
    passed: bool
    hard: bool
    detail: str


def probe_1_abort_before_a_model_call(host: Host) -> Verdict:
    """The ceiling case. Refuse at turn 1; the model must never be reached."""
    model = FakeModel()

    def before_call(turn: int) -> None:
        raise Refusal("ceiling reached before the first call")

    run = host.run(model, max_iterations=3, before_call=before_call)
    passed = model.calls == 0 and isinstance(run.raised, Refusal)
    return Verdict(
        1, "a callback can abort BEFORE a model call", passed, hard=False,
        detail=(f"model called {model.calls}x (want 0); "
                f"raised={type(run.raised).__name__ if run.raised else None} (want Refusal)"),
    )


def probe_2_abort_at_an_iteration_boundary(host: Host) -> Verdict:
    """Let two turns through, refuse at the third boundary. Exactly two calls."""
    model = FakeModel()

    def before_iteration(turn: int) -> None:
        if turn >= 3:
            raise Refusal(f"stopped at iteration {turn}")

    run = host.run(model, max_iterations=6, before_iteration=before_iteration)
    passed = model.calls == 2 and isinstance(run.raised, Refusal)
    return Verdict(
        2, "a callback can abort AT AN ITERATION BOUNDARY", passed, hard=False,
        detail=(f"model called {model.calls}x (want 2); "
                f"raised={type(run.raised).__name__ if run.raised else None} (want Refusal)"),
    )


def probe_3_the_models_exception_propagates(host: Host) -> Verdict:
    """The model breaks on call 1. The SAME exception must reach the caller,
    and the host must not have tried again — a retry here is how a run ends
    up answered by a backend nobody recorded."""
    model = FakeModel(raises_on_call=1)
    run = host.run(model, max_iterations=4)

    propagated = isinstance(run.raised, ModelBroke)
    no_retry = model.calls == 1
    passed = propagated and no_retry
    return Verdict(
        3, "the model's exception PROPAGATES, unretried", passed, hard=False,
        detail=(f"raised={type(run.raised).__name__ if run.raised else None} (want ModelBroke); "
                f"model called {model.calls}x (want 1 — more means a silent retry)"),
    )


def probe_4_an_abort_still_records_the_spend(host: Host) -> Verdict:
    """HARD FAIL. Spend on two turns, then refuse before the third call. The
    host's ledger must carry what those two turns actually cost."""
    model = FakeModel()

    def before_call(turn: int) -> None:
        if turn >= 3:
            raise Refusal("ceiling reached mid-run")

    run = host.run(model, max_iterations=5, before_call=before_call)

    spent_in, spent_out = model.tokens_in, model.tokens_out
    recorded = run.ledger.tokens_in == spent_in and run.ledger.tokens_out == spent_out
    passed = bool(spent_in) and recorded and run.ledger.finished
    return Verdict(
        4, "an abort STILL RECORDS the spend", passed, hard=True,
        detail=(f"actually spent in/out {spent_in}/{spent_out}; "
                f"ledger recorded {run.ledger.tokens_in}/{run.ledger.tokens_out}; "
                f"finished={run.ledger.finished}"),
    )


PROBES = [
    probe_1_abort_before_a_model_call,
    probe_2_abort_at_an_iteration_boundary,
    probe_3_the_models_exception_propagates,
    probe_4_an_abort_still_records_the_spend,
]


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

def _langgraph_host():
    """Imported lazily: the harness must run on a box with no candidate
    installed, and report a skip rather than a failure."""
    from orchestrator_hosts.langgraph_host import LangGraphHost  # type: ignore

    return LangGraphHost()


HOSTS: dict[str, Callable[[], Any]] = {
    "null": NullHost,
    "broken": BrokenHost,
    "langgraph": _langgraph_host,
}


def run_host(name: str) -> int:
    try:
        host = HOSTS[name]()
    except Exception as exc:                    # noqa: BLE001
        print(f"{name}: SKIP — cannot construct ({exc})")
        return 3

    reason = host.available()
    if reason:
        print(f"{name}: SKIP — {reason}")
        return 3

    # SAY WHAT WAS MEASURED. Found 2026-08-17: the operator's global python
    # carried an undeclared langgraph 1.1.10 that nobody installed on purpose,
    # so a bare `python3 tools/orchestrator-acceptance.py --host langgraph`
    # measured THAT and reported a clean pass — for a version the spike never
    # chose. The stack has been removed, which closes today's instance and not
    # the shape: a result that does not name its subject can always be a
    # result about something else.
    print(f"\n  host: {name}")
    print(f"  interpreter: {sys.executable}")
    provenance = getattr(host, "provenance", None)
    if callable(provenance):
        print(f"  subject:     {provenance()}")
    print("  " + "-" * 68)
    failures = 0
    hard_failures = 0
    for probe in PROBES:
        try:
            verdict = probe(host)
        except Exception:                       # noqa: BLE001
            print(f"  [{probe.__name__}] ERRORED:\n{traceback.format_exc()}")
            failures += 1
            continue
        mark = "PASS" if verdict.passed else ("HARD FAIL" if verdict.hard else "FAIL")
        print(f"  {verdict.item}. {verdict.title:<46} {mark}")
        print(f"     {verdict.detail}")
        if not verdict.passed:
            failures += 1
            hard_failures += int(verdict.hard)

    print("  " + "-" * 68)
    if hard_failures:
        print(f"  {name}: REFUSED — {hard_failures} hard failure(s). "
              "A host that loses the tally on an abort is not a candidate.")
        return 2
    if failures:
        print(f"  {name}: {failures} of {len(PROBES)} items failed.")
        return 1
    print(f"  {name}: all {len(PROBES)} items pass.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", action="append", help="candidate to test (repeatable)")
    ap.add_argument("--list", action="store_true", help="list known candidates")
    args = ap.parse_args()

    if args.list:
        for name in HOSTS:
            print(name)
        return 0

    names = args.host or ["null", "broken"]
    worst = 0
    for name in names:
        if name not in HOSTS:
            print(f"unknown host {name!r}; known: {', '.join(HOSTS)}", file=sys.stderr)
            return 2
        worst = max(worst, run_host(name))
    print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
