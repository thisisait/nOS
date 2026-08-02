---
name: loop
description: Run one bounded improvement cycle over the nOS estate — mine a weakness, propose one change, make it, have it judged, report the verdict. Use when asked to run the loop, improve something, or close a weakness end to end. One cycle per invocation.
---

# loop — the ceremony, and nothing else

This file contains no address, no token, no threshold and no rule. Every step is
delegated to the skill that owns it, and everything those skills could decide,
the engine already decided. That is what makes this ceremony reproducible from
Hermes with no Claude in the picture — and anything you add here is something
Hermes will not have.

## The cycle

1. **`weakness-scan`** — ask what is wrong. Take the ranking as given.
2. **Pick one item.** The top item you can actually act on. If the list came back
   incomplete or degraded, say so before choosing; a partial list is a partial
   choice.
3. **`propose`** — record the change *before* making it. If it is refused, the
   cycle ends there; report the engine's reason.
4. **Make the change.** Exactly the declared paths. Exactly one change.
5. **`judge`** — trigger the gate set and wait for the verdict.
6. **Report.** The verdict, verbatim, with its run id and per-judge evidence.

Then **stop.** One weakness, one change, one verdict. Two changes under one
verdict teach nothing about either, and a cycle that keeps going until it finds a
green one is a search for a verdict rather than a test of a change.

## Where the cycle ends early

Stop and report — do not route around, do not retry differently, do not fall back
to doing the step by hand:

- a refusal (`409`), a wrong-identity answer (`403`), an unconfigured host (`503`),
  or a route that is not mounted (`404`);
- a verdict of `fail` — the change did not hold; that is a result, and it is
  recorded, and it is worth more than a change that was quietly reverted;
- a verdict of `indeterminate` — a judge did no work or could not run. Nothing is
  known about the change. Do not treat it as a near-pass and do not "try again
  until it goes green";
- a proposal the engine flags as needing an operator. Hand it over as flagged.

## What this cycle does not do

It does not apply, commit, merge or deploy. It proposes and it judges. A green
verdict is information for an operator, not a licence.

It does not schedule itself. Cadence belongs to Pulse, and only after enough
attended cycles to trust the parts.

It does not touch the per-session propose/evaluate loop that already exists in
AgentKit. This ceremony lives strictly *between* sessions.

## What counts as having worked

Not "the loop ran". A weakness that was on the list, is not on the list, and the
verdict that removed it was produced by a judge the proposer could not touch —
**and the verdict replays.** Anything short of that is a loop reporting its own
success, which is the defect it exists to detect.
