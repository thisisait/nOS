# 15 — the loop records a lineage whose first link does not join

**Status:** OPEN. Found 2026-08-07 while building the ledger's flow board — the
board could not draw the column it was designed around.

## The fee

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
