"""What a journey owes the estate it touches (2026-08-19).

MEASURED, twice, same root. `test_approval_flow` POSTs an approval question as
`e2e-mock-agent`; the repository files an `Agent asks:` notification with it.
The journey had no teardown, so 29 green runs between 2026-08-11 and 08-16 left
29 permanent HIGH rows in the operator's inbox — the single largest block of
the 69-unread triage. One layer over, 60 orphaned `nos-tester-e2e-*` Authentik
accounts accumulated the same way: the cleanup existed but nothing verified it
had run, and nothing failed when it had not.

An e2e journey mutates the LIVE estate — that is the point of it — so the
harness, not each journey's discipline, must carry three guarantees:

  PREFLIGHT   Before the journey starts, its residue probes are run. Residue
              from ANY earlier run — including one that was SIGKILLed with no
              chance to clean up — fails THIS run with the leak named. This is
              how the estate learns within one run instead of two weeks later
              in an unrelated triage: a crash cannot report itself, so the
              next run reports it.

  UNDO        Every estate mutation is registered WHEN IT IS MADE, with the
              callable that undoes it. The harness unwinds in reverse order on
              exit — success, assertion failure, or exception alike. An undo
              only ever registered "after the test passes" is the defect this
              file exists to remove.

  POSTFLIGHT  After unwinding, the probes run AGAIN. Cleanup does not report
              its own success (the estate's hardest-won rule); the probe reads
              the estate and says what is still there. Residue after cleanup
              fails the run even if every step passed.

A probe is a READER: it returns identifiers and never deletes anything. An
unreadable estate raises from the probe itself — absence of an answer is not
absence of residue.

Pinned by tests/anatomy/test_journey_residue_contract.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class ResidueLeakError(AssertionError):
    """A journey (this run or an earlier one) left objects in the live estate."""


class UndoFailedError(AssertionError):
    """A registered undo could not be executed; the estate may hold residue."""


@dataclass
class ResidueProbe:
    """A read-only question to the estate: 'what did this journey leave?'

    ``find`` returns identifiers of matching residue (empty list = clean) and
    must RAISE when the estate cannot be read — an unanswerable probe is not a
    clean one.
    """

    name: str
    find: Callable[[], list[str]]


@dataclass
class Mutation:
    """One estate object a journey created, and how to take it back."""

    kind: str
    ref: str
    undo: Callable[[], None]


@dataclass
class ResidueLedger:
    """Per-journey undo stack + probe runner. Owned by the harness."""

    journey: str
    probes: tuple[ResidueProbe, ...] = ()
    mutations: list[Mutation] = field(default_factory=list)

    def register(self, kind: str, ref: str, undo: Callable[[], None]) -> None:
        self.mutations.append(Mutation(kind=kind, ref=ref, undo=undo))

    def preflight(self) -> None:
        """Fail BEFORE mutating if any earlier run leaked. The crashed run
        could not report itself; this run does it for them."""
        leaked: list[str] = []
        for probe in self.probes:
            found = probe.find()
            leaked.extend(f"{probe.name}: {ref}" for ref in found)
        if leaked:
            raise ResidueLeakError(
                f"journey '{self.journey}' refuses to start: a previous run "
                f"leaked {len(leaked)} object(s) into the live estate — "
                + "; ".join(leaked)
                + ". Clean them up (or let this journey's undos be fixed) "
                "before running again; starting anyway would bury the leak "
                "under fresh residue."
            )

    def unwind(self) -> list[str]:
        """Run every undo, newest first. Returns failures; never raises —
        the caller decides whether an in-flight test exception outranks."""
        errors: list[str] = []
        for m in reversed(self.mutations):
            try:
                m.undo()
            except Exception as exc:  # noqa: BLE001 — every undo must get its turn
                errors.append(f"{m.kind} {m.ref}: {type(exc).__name__}: {exc}")
        return errors

    def postflight(self) -> list[str]:
        """Re-read the estate AFTER unwinding. The undo code does not get to
        say it worked; the probe says what is actually there."""
        remaining: list[str] = []
        for probe in self.probes:
            found = probe.find()
            remaining.extend(f"{probe.name}: {ref}" for ref in found)
        return remaining
