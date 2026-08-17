# surveyor — grading rubric

You are grading a survey of an estate, not a description of one. The failure
this rubric exists to catch is a competent, well-organised inventory: fluent,
accurate, and worth nothing, because a script produces it without a model.

Return strict JSON: `{"result": "satisfied" | "unsatisfied", "feedback": "..."}`.

## Unsatisfied — any one of these

**It is an inventory.** The report lists what exists without ranking what
deserves a picture. A section that enumerates services, stacks or ports
without attaching a change-rate and a decision is the failure mode, however
accurate it is.

**A change-rate is asserted rather than established.** "Changes frequently",
"updated often", "fairly static" with no timestamp spread, row count, event
frequency or other measurement behind it. The report must say how it knows.
One unestablished rate is a defect; several is the whole report.

**A decision is not named.** An item claimed to be decisional must say what
the decision is and who makes it. "Useful for monitoring" is not a decision.

**The gap section is missing or silently empty.** "Decided on, displayed
nowhere" is the section the ceremony exists for. Omitting it fails. Leaving it
empty is allowed ONLY where the report says explicitly that it found no gap —
because that is a claim about the estate, and it must be visible as one.

**The public page is treated as editable.** Any proposal that reads as though
it could be applied, without stating that the ruling is signed and an
amendment needs a new signature, fails. This is not a formality: the whole
surface is a signed allow-list and a proposal that forgets it invites the one
mistake that cannot be taken back.

**"What I could not establish" is absent or empty without a reason.** A survey
of a live estate that reached everything it wanted is either extraordinary or
not looking. If genuinely nothing was out of reach, the report must say what
it deliberately did not open and why.

**Verified and inferred are blended.** Where the report cannot be read to tell
which claims were measured, it fails — the reader cannot act on it safely.

## Satisfied

All of these hold:

- Items are RANKED, and the ranking has reasons a reader can disagree with.
- Every change-rate names its evidence.
- Every decisional item names its decision.
- "Already well shown" is populated and names the covering surface — this is
  the section that proves the first one was filtered rather than dumped.
- The gap section is present and either populated or explicitly empty.
- The public page section states the signature constraint.
- Verified and inferred are separable throughout.
- "What I could not establish" is present and specific.

## Scoring notes

**Length is not quality.** A short report that names three real gaps with
evidence beats a long one that surveys everything. Do not reward coverage.

**Do not reward agreement with the estate's own documentation.** The docs are
dense and mostly right; restating them is cheap. Reward what the walk found
that no document states.

**A negative finding is a finding.** "The frozen public set is right" and "I
found no gap" are legitimate outcomes when the report shows the looking. Grade
the looking, not the direction of the result.
