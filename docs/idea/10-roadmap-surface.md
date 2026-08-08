# 10 — The roadmap surface

**Status: the table is live; the prose roadmap it replaces is stale.**
**Detail:** [`roadmap-table.md`](../archive/roadmap-table.md) ·
**Seeder:** `tools/roadmap-seed.py`

## The split

**The table is the state. These documents are the argument.**

| | holds | lives in |
|---|---|---|
| `nOS Roadmap` DataTable | dates, statuses, nesting, citations | KEAP, seeded by `tools/roadmap-seed.py` |
| `docs/idea/` | why, what is true, what is open | git, hard ceiling of twenty |
| `docs/archive/` | what happened and what never did | git |

Duplicating dates or statuses into prose is how the previous surface drifted.
**The prose roadmap was retired on 2026-08-07** and its 638 lines are at
[`../archive/roadmap-2026q3.md`](../archive/roadmap-2026q3.md); `docs/roadmap.md`
is now a pointer plus the v1.0 exit criteria, which are the one thing a table row
cannot hold. What decided it was not the stale mermaid chart named here five days
earlier, but a count: of the workstreams live that week — SERE, the genome,
hydrators, cortex-lang, the Planner, relations, the fee ledger — the 638 lines
mentioned **none**, while the table carried a row for each.

## The table

**60 rows** as of 2026-08-07 (38 when this file was written), self-nesting via a
`parent` slug, because an epic and a step are the same shape and depth is not
fixed at two. Ask it — do not restate it:

```bash
tools/roadmap-status.py [--all] [--track <t>] [--schema] [--json]
```

That reader is newer than the table by five days. Until 2026-08-07 the table
could only be written, which is why the review that found the divergence below
had to be done with hand-written curl.

Its integrity is **seed-gated, not schema-enforced**: KEAP has no `rowRef` kind,
so a parent is a plain slug and a typo would render as a phantom root. The seeder
refuses orphans and duplicates instead.

## The definition describes a table that does not exist

The blocker this section used to record — *"no L1 concept accepts `kind: date`"* —
cleared with KEAP v1.39.0, and `state/keap-tables/roadmap.table.yml` was written.
**Nothing ever applied it.** Measured 2026-08-07:

| | |
|---|---|
| declared in git | 23 columns |
| live on the table | 9 |
| declared but absent | `kind` `verified` `verified_by` `verified_at` `evidence` `target` `occurred_at` `severity` `effort` `owner` `source` `source_ref` `anchor` `embedding` `ordinal` |

The playbook seeds only the three `face-*` tables
(`roles/pazny.keap/tasks/seed-face-tables.yml`), and the roadmap is carved out of
that gate's coverage by `UNSEEDED` in `test_keap_table_concepts.py` — whose
stated reason is about **rows** ("rows come from `tools/roadmap-seed.py`") while
what is unapplied is the **definition**. The carve-out was doing more work than
its reason claimed.

The cost is not cosmetic. `verified` exists so a row can say *someone claims this
shipped and a probe disagrees* — the separation the definition's own header calls
the point of the table. That column is in git and not in the database, so no row
can say it, and all 60 carry `verified: None`.

Two further divergences were found the same hour and are now closed in git:
the seeder wrote three `status` values the definition did not list (`active`,
`next`, `parked` — so applying the definition would have **rejected every row its
own writer produces**), and it wrote a single `when` where the definition splits
`target` from `occurred_at`. Declaring a deprecated `when` was tried and refused
within the hour by `test_keap_table_concepts.py`: two columns may not claim one
concept, and the L1 vocabulary has no name for a date that is sometimes a plan and
sometimes a fact. The writer migrated instead, and now preflights the live schema
and exits non-zero naming the missing columns rather than writing into a shape the
definition has moved past. Pinned by
`tests/anatomy/test_the_roadmap_declares_the_table_it_fills.py`.

**What is open:** applying the definition to the live table. That is a live
migration of the operator's board, not a converge side-effect, and it is the
remaining half of v1.0 exit criterion 6.

## Agent-filed rows skip the lane built for them

The definition reserves `inbox` → `triaged` for agent-filed observations, so that
*"an agent cannot start work simply by filing it"*. The seven `obs-*` rows the
discovery scan has filed are all `queued`, straight past both. Four of them name
REMs closed on 2026-08-06 and no longer true; two report a working-tree diff in
counts (`0 rows on disk, 0 at HEAD`) that says nothing. Nothing retires an
observation once its cause is gone — the filing path has a writer and no reader.

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

**Twenty documents in `docs/idea/`** (ten until 2026-08-02; raised the same day
rather than forcing a merge that was not wanted). At the ceiling, one absorbs the
next or one is finished and moves to the archive. The previous surface reached 20 390 lines
because nothing ever forced that choice.

**At the next release**, reconcile `docs/archive/` and delete what has no
successor — deliberately, as a decision, not as a cleanup that drifts.
