---
description: Run one bounded nOS improvement cycle — mine a weakness, propose one change, have it judged, report the verdict.
argument-hint: "[gate-set]  (default: fast)"
---

# /loop-improve

Run **one** cycle of the nOS agentic loop, out loud, using the `loop` skill.
Gate set: `$ARGUMENTS` if given, otherwise the engine's default first-cycle set.

Show the operator each of the four addresses as it is called and what came back —
this command exists to be watched. Then report:

- the weakness chosen, with its id, and whether the scan was complete;
- the proposal uuid and fingerprint, or the refusal, verbatim;
- the change, as a diff;
- the verdict — `pass`, `fail` or `indeterminate` — with the run id and the
  per-judge evidence.

Do not apply, commit or merge anything. Do not run a second cycle. If any step
refuses or the verdict is not `pass`, that is the report — say it plainly and
stop.
