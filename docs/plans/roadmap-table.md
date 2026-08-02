# The nOS roadmap DataTable

> Built 2026-08-02 at the operator's request: a timeline-style quick overview
> with references to concrete plans, workflows and release versions, extendable
> over time, with steps nestable under a parent.

---

## 1. One table, not two — and the reason is a measurement

The operator asked: *two tables, or a list plus records with an optional parent
id?*

**One table, with an optional `parent` column.** Reasons, in order of weight:

1. **A roadmap item and a sub-step are the same kind of thing.** Both have a
   date, a status, a track, references and prose. Two tables would duplicate the
   schema, the view config, the seeder and the fixture — and then drift.
2. **Depth is not fixed at two.** "P1 — HKDF" is a step under "Secrets", but it
   has its own steps (scout, design, wire, gate). A two-table model caps the
   tree at one level on day one.
3. **The two views fall out of one shape.** Timeline filters to
   `parent == ""`; the tree expands children. No join.

### The cost, stated rather than hidden

**KEAP has no `rowRef` column kind.** Verified 2026-08-02 — the enum is
`text · number · boolean · date · select · json · file · vector · taxonomyRef ·
objectRef · user`. The `table_row_refs` table that
`nos-genome-and-organelles.md` refers to **does not exist in the KEAP source
either**; that reference is aspirational and should be corrected there.

So `parent` is a plain `text` column holding a sibling's slug, with **no
referential integrity**. A typo produces an orphan that renders as a phantom
root. Mitigation: the seeder refuses to write if any non-empty `parent` does not
resolve to a slug in the same batch, and refuses duplicate slugs. That check is
in the seeder because the schema cannot carry it — which is exactly the kind of
thing to write down rather than discover later.

If `rowRef` is ever added, `parent` upgrades in place with no data migration:
the values are already slugs.

## 2. Why it is NOT a fixture yet — a gap in the L1 vocabulary

The table is live and seeded (38 rows, 14 top-level, 24 nested). It is **not** in
`state/keap-tables/` yet, and adding it today would turn CI red for a reason
worth understanding.

`tests/anatomy/test_keap_table_concepts.py` requires every fixture column to
declare an L1 `concept:` drawn from the closed, git-owned vocabulary. Measured
against that vocabulary:

```
kinds any concept accepts:
  boolean, json, number, objectRef, select, taxonomyRef, text, user, vector

concepts accepting kind 'date':
  NONE
```

**There is no temporal concept in L1.** Not one of the 36 accepts a `date`. And
no existing fixture has ever had a date column, which is why the gap has never
been hit.

The consequence is structural, not cosmetic: **a timeline table cannot be a
fixture**, because the column the timeline is built on has no legal meaning.

### The fix, and why it is a coordinated change

Add one concept — proposed `time.occurred_at`, `kinds: ['date']`, *"When the
thing the row describes happened or is planned for."* Possibly a sibling
`time.due_at` later; one is enough now.

It touches two places and both must move together:

1. `keap/src/shared/contracts/field-concepts.ts` — KEAP validates concepts at
   write time, so an unknown one is rejected by the API.
2. `files/anatomy/cortex/shared/contracts/field-concepts.ts` — the vendored copy
   the nOS gate reads.

That means a KEAP tag + `keap_repo_ref`/`keap_version` bump (both halves, per
the version-pin-shadow rule) + a re-vendor. Additive and low risk, but it is a
release action, so it belongs in a converge the operator is present for — the
blank planned for 2026-08-03 is the natural moment.

**Until then the table is live and useful; it simply is not reproducible from
git.** A fresh blank would not recreate it. That is the honest status.

## 3. Schema

| column | kind | role | purpose |
|---|---|---|---|
| `slug` | text | dimension | stable key; what `parent` points at |
| `title` | text | attribute | the line you read in the timeline |
| `parent` | text | dimension | empty = top-level; otherwise a sibling's slug |
| `when` | date | dimension | the timeline axis |
| `status` | select | dimension | shipped · active · next · queued · blocked · parked · dropped |
| `track` | select | dimension | release · security · cortex · face · filesystem · platform · agents · observability · compliance · infra |
| `release` | text | dimension | the tag it shipped in, or is aimed at |
| `refs` | text | attribute | plan doc · workflow · REM id · test — the citation |
| `body` | text | attribute | the timeline's prose body |

`view`: `timeline`, title `title`, body `body`, date `when`, meta
`status/track/release`.

## 4. The seeding rule

**Every row cites something that exists** — a plan doc, a workflow file, a git
tag, a REM id, a test. A row that cannot cite anything is an opinion, and
opinions do not belong in a roadmap that other work will be planned against.

## 5. What the consolidation surfaced

Reviewing `docs/plans/`, `docs/llm/` and the workflow sets produced three
findings that are themselves roadmap rows:

- **38 of the 68 plan docs are `v07-*`, and essentially none were implemented.**
  They all name a target branch `feat/v0.7-overnight`, which has **zero commits
  not already in master**. They read as a plan and are not one. Either fold the
  live ones into the backlog or archive them — `docs/plans/` currently overstates
  what is planned by roughly a factor of two.
- **`docs/roadmap.md`'s mermaid trajectory is stale**: its "Now" is v0.9-beta
  staging, two releases behind. This table is intended to replace that chart as
  the living surface; the prose roadmap keeps the argument, the table keeps the
  state.
- **Commit signing is required by the master ruleset and has never once been
  satisfied** — the v0.10 push logged `Found 188 violations` and admin-bypassed.
  A rule that only ever reports its own defeat is the same shape as everything
  v0.10-beta was named after.
