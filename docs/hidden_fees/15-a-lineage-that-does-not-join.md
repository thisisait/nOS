# 15 — the loop records a lineage whose first link does not join

**Status: WRITE HALF PAID 2026-08-16, verified 2026-08-18. Read half open.**

> **The fee below describes the estate as it was on 2026-08-07 and is kept for
> the reasoning, not the facts.** Re-measured 2026-08-18 before touching
> anything — which is how this was noticed at all:
>
> ```sql
> SELECT weakness_id, COUNT(*), MIN(date(created_at)) FROM loop_proposals GROUP BY 1;
> -- rem:REM-159  2  2026-08-16
> -- rem:REM-204  1  2026-08-16
> -- w1           8  2026-08-02
> -- w2           1  2026-08-02
> ```
>
> The proposer now cites real ids that join to the registry. It cannot do
> otherwise: `Ledger._weakness_evidence_sha` raises
> `ProposalRefused("unknown-weakness")` for any id no source reports, on the
> propose path (`ledger.py:879, 986`), gated twice
> (`test_loop_ledger.py:896`, `test_loop_ratchet_inputs_are_derived.py:328`).
> A proposal claiming `w1` is now impossible rather than merely discouraged.
>
> That refusal arrived for a DIFFERENT reason — §4's retry ceiling was keyed on
> two fields a grinder could vary, so the sha had to be looked up rather than
> accepted — and closing this fee was a side effect nobody recorded. The nine
> `w1`/`w2` rows are pilot residue from one day in August, not a live defect.
>
> **What remains is the half this entry named last and buried:** *"Which
> weakness sources actually produce proposals?"* is still unanswerable, because
> nothing reads the join even now that it resolves. A source that has never led
> anywhere still looks exactly like one that leads everywhere. See
> `tools/loop-status.py` (2026-08-18) for the reader, and "What paying it looks
> like" below for why a gate was deliberately not the answer.

## The fee (as measured 2026-08-07)

The loop's whole claim is a chain: **a weakness is detected → a proposal is
raised against it → judges rule → a verdict is sealed.** Three of those four
links are recorded and joinable. The first is not.

`loop_proposals.weakness_id` holds `w1` and `w2`. The weakness registry — Bone's
`SOURCE_ORDER` in `files/anatomy/bone/weaknesses.py`, which the anatomy graph
compiles into seven `weakness:*` nodes — names its sources
`weakness:corpus-diff`, `weakness:hidden-fees`, `weakness:remediation-queue`,
`weakness:scan-state`, `weakness:pulse-runs`, `weakness:prometheus-alerts`,
`weakness:git-worktree`. Nothing in the ledger cites any of them.

Measured 2026-08-07 against `~/wing/app/data/wing.db`:

```sql
SELECT weakness_id, count(*) FROM loop_proposals GROUP BY weakness_id;
-- w1|8   w2|1
SELECT DISTINCT date(created_at) FROM loop_proposals;
-- 2026-08-02
```

All nine proposals are from one pilot day, and both ids are placeholders. The
column is populated, typed, non-null and joins to nothing.

## Why it is a fee and not a bug

Nothing fails. The proposals exist, the judge runs exist, the verdicts exist,
and every screen that reads them renders. `loop_proposals` has no foreign key to
assert against and the weakness registry lives in a different process (Bone) and
a different artifact (the graph), so there is no layer whose job it is to
notice. The ledger's own tables are internally consistent — which is exactly the
property that makes this invisible.

## When the bill comes due

- **The first real autonomous run.** The loop's value is that a change can be
  traced back to the observation that motivated it. With placeholder ids that
  trace stops one step in, and the answer to "why did the estate change itself"
  is `w1`.
- **Any surface that draws the lineage.** The flow board was designed with a
  weakness column and shipped without one, because rendering it would have drawn
  a genealogy the data does not contain. The next surface will face the same
  choice, and may not notice it is making one.
- **Judging the loop's own quality.** "Which weakness sources actually produce
  proposals?" is the question that tells you whether a detector earns its run.
  It is unanswerable today, so a source that has never once led anywhere looks
  exactly like one that leads everywhere.

## How it was found

Sideways, per the entry test. The board was being built from
`docs/archive/nos-anatomy-graph.md`'s variant-C shape (weakness → proposal →
verdict, non-selected lineage dimmed). Joining column one to the registry
returned nothing, and the check that would have caught it earlier — a screen
that renders the join — did not exist until the moment it failed.

The face now names the gap rather than drawing over it: unresolvable ids render
as a warn-toned finding above the proposal list.

## What paying it looks like

Not a foreign key. `loop_proposals` is written by Bone and the registry is
Bone's own — the cheap half is that the proposer cites the id it already holds
instead of a placeholder. The harder half is deciding what a proposal raised by
an operator, or by a source outside the registry, records instead; `w1` is at
least honest about being nothing, and a wrong registry id would be worse.

A gate belongs on the join once real rows exist, not before: with nine pilot
rows it would only pin the placeholder.
