# 06 — The genome and its organelles

**Status: L1 shipped in v0.10-beta. The generator emits 2 of the 4 targets B1
promised. `rowRef` and `table_row_refs` — referenced by the plan — do not exist
in KEAP.**
**Detail:** [`nos-genome-and-organelles.md`](../archive/nos-genome-and-organelles.md) ·
[`datatables-relations.md`](../archive/datatables-relations.md) ·
[`keap-datatables-apps-systems.md`](../archive/keap-datatables-apps-systems.md)

## The problem it exists to remove

The same law was restated by hand in every organ that needed it:

| law | restated in | worst symptom |
|---|---|---|
| RBAC tier → group | **7 places, 5 languages** | a live shape mismatch masked by `\| default()` |
| GDPR Art-30 | 4 declarations | two inverse spellings of one fact |
| face ↔ KEAP contracts | hand-mirrored, no gate | already drifted — 11 kinds vs 12 |
| **exposure / gating** | **5 places** | **REM-144** |

Across the eight files in `state/schema/` there was **not one `$ref`, `allOf` or
`$defs`.** Zero composition.

## What shipped

- **`state/genome/entity.schema.json`** — a base entity with `identity` /
  `compliance` / `access` / `cortex` / `face` facets, composed by `$ref` +
  `allOf`. The first cross-file `$ref` in the estate.
- **The `access` facet** reconciles the five declarations of "how is this
  reached and what gates it" — the split that produced REM-144.
- **L1 field concepts** — a closed, git-owned vocabulary; all 76 columns of the
  five table definitions carry a `concept:`.
- **The write path `data_tables.schema_json` never had.** Until then a table's
  columns were immutable for its lifetime, so a changed definition was a silent
  no-op on every converged install.

## What is NOT true, and was claimed

- **32 of the 76 L1 columns reach a database, not 76.** The seeder enumerates
  three slugs; `apps` (23 cols) and `systems` (21) are annotated in git and
  belong to tables that do not exist on a converged host. `keap_nos_full_catalog`
  — the flag that reads as if it seeds the rest — is declared, set by
  `profiles/all-on.yml`, and **read by nothing**.
- **The generator emits 2 of 4 targets.** The Wing `Entity.php` and the cortex
  zod contract do not exist.
- **`rowRef` does not exist** as a column kind, and neither does the
  `table_row_refs` table the plan cites. Verified 2026-08-02. Any parent/child
  or N:N relation is a slug in a `text` column with no referential integrity —
  gate it in the seeder, because the schema cannot.
- **No concept accepts `kind: date`.** None of the 36. A timeline table
  therefore cannot be a fixture until `time.occurred_at` exists in KEAP *and*
  the vendored copy. This is the live blocker on [07](07-face.md)'s roadmap table.

## The rule that must not erode

> Facts about an entity → data, declared once, inherited, generated everywhere.
> What may **act** on an entity → code, per runtime, hash-compared, never
> inherited from a manifest and never addable by declaring it.

## Next

`time.occurred_at` (small, coordinated, both sides) · `syncRows` · the two
missing codegen targets · then collapse a second facet, not a fifth copy of one.

**The edges are the next facet, and they are surveyed.**
[`docs/archive/nos-anatomy-graph.md`](../archive/nos-anatomy-graph.md) (2026-08-06)
inventories what the estate already wires implicitly — 28 data, 38 trigger,
2 resource claims, 7 temporal — every row cited to `file:line` or to a
`wing.db` query, and proposes `depends_on` in the manifest beside `category`,
one kind-prefixed address space, and `state/anatomy-graph.json` compiled by
regenerate-and-diff. Two findings from it are already fixed: the halt that
three documents described and no code performed, and the claude mutex that one
of two spawners took.

Its rule is the one to carry forward: **repair before declare.** A graph that
records what the code stopped doing is the estate's signature defect with a
schema around it, so every edge carries `measured:` and is authored by a
measurement pass, not by reading a comment.
