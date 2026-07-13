# Curator report rubric

The grader scores a curator sweep against structural discipline and
evidence, the same bar the librarian's judgments meet.

## Structure

- Report under heading `## Curator report`.
- Three sub-sections, in order: `Summary`, `Proposals`, `Skips`.
- `Summary` states: batch size, nodes judged, nodes flagged, proposals
  posted, per-item errors, frontier remaining.

## Proposals contract

Each bullet under `Proposals` MUST include:

1. **Node** — the node id + name the rewrite targets.
2. **Defect** — the concrete reason the old description failed: `stub`,
   `circular` (names the label not the concept), `house-style` (hedging /
   meta-language / wrong register), or `boundary` (does not carve against a
   named sibling). "Could be better" is not a defect and returns
   `needs_revision`.
3. **What changed** — one clause on how the rewrite fixes the defect
   (concept named, boundary drawn, register corrected).

## No-churn check

- A proposal that rewrites an already dense, encyclopedic,
  boundary-carving description without a named defect returns `failed`.
  The curator repairs defects; it does not restyle fine text.

## Propose-only check

- The report MUST NOT claim any node was modified, renamed, deleted, or
  approved. The curator proposes; the moderator decides. Language asserting
  a completed edit returns `failed`.

## Checkpoint check

- Every node in the batch must be accounted for — flagged (with a proposal)
  or skipped as fine (counted in `Skips`). A batch that judged N nodes but
  checkpointed fewer returns `needs_revision` (the cursor did not advance).

## Exit-code framing

- `NOS_AGENT_EXIT: 1` is reserved for a **structural finding queued for
  operator review** (a duplicate or misparent P0 cannot repair). Using
  exit 1 for routine rewrite proposals awaiting moderation returns
  `needs_revision` — that is the exit-0 normal outcome.

## Empty-frontier case

If the frontier returns zero nodes (all recently swept + unchanged), the
report is exactly:

```
## Curator report

### Summary
Frontier: 0 nodes (all within cooldown, unchanged). Judged: 0. Proposed: 0.

### Proposals
_None — frontier empty._

### Skips
_None._

NOS_AGENT_EXIT: 0
```
