# 10 — The roadmap surface

**Status: the table is live; the prose roadmap it replaces is stale.**
**Detail:** [`roadmap-table.md`](../archive/roadmap-table.md) ·
**Seeder:** `tools/roadmap-seed.py`

## The split

**The table is the state. These documents are the argument.**

| | holds | lives in |
|---|---|---|
| `nOS Roadmap` DataTable | dates, statuses, nesting, citations | KEAP, seeded by `tools/roadmap-seed.py` |
| `docs/idea/` | why, what is true, what is open | git, ten files, hard ceiling |
| `docs/archive/` | what happened and what never did | git |

Duplicating dates or statuses into prose is how the previous surface drifted —
`docs/roadmap.md`'s mermaid trajectory still shows "Now: v0.9-beta staging", two
releases behind.

## The table

38 rows, 14 top-level, 24 nested, timeline style. **One table, self-nesting via a
`parent` slug**, because an epic and a step are the same shape and depth is not
fixed at two.

Its integrity is **seed-gated, not schema-enforced**: KEAP has no `rowRef` kind,
so a parent is a plain slug and a typo would render as a phantom root. The seeder
refuses orphans and duplicates instead.

**It is not a fixture** — no L1 concept accepts `kind: date`, so a timeline table
cannot live in `state/keap-tables/` until `time.occurred_at` exists in KEAP and
in the vendored copy. Live and useful; not reproducible from a blank.

## The seeding rule

**Every row cites something that exists** — a plan, a workflow, a tag, a REM id,
a test. A row with nothing to cite is an opinion, and other work gets planned
against this table.

## What the 2026-08-02 consolidation found

- **38 of 69 plans were `v07-*`**, 11 230 lines, all naming a branch with **zero
  commits not already in master**. `docs/plans/` overstated planned work by
  roughly a factor of two for seven weeks.
- **Link integrity was measured, not assumed**: 23 broken markdown links before
  the move, 5 after — and 4 of those 5 live inside the document whose subject
  *is* a broken link.
- **A plan that names a branch should be checked against that branch.** Nothing
  compared the claim to the repository.

## The standing constraint

**Ten documents in `docs/idea/`.** An eleventh idea means one absorbs it, or one
is finished and moves to the archive. The previous surface reached 20 390 lines
because nothing ever forced that choice.

**At the next release**, reconcile `docs/archive/` and delete what has no
successor — deliberately, as a decision, not as a cleanup that drifts.
