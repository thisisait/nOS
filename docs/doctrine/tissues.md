# Tissues — the transplantable pack of one specialization

> **PROPOSED** (2026-10-06, roadmap row `tissues`). Nothing here is in force
> until the operator rules on it. The word is settled in
> `state/genome/lexicon.yml`; this file settles what the word holds.

## 1. What a tissue is

A **cell** is one model in one specialization (in code, an agent). A **tissue**
is everything one specialization needs to do its work, gathered in one file:
its cells, the skills they read, the tables they write, the services behind
them, the reflexes (Pulse jobs) that run on a clock, the doors data comes in by,
and the reference knowledge it starts with.

Why it exists: a firm buys "the accounting system" from a vendor and is then
tied to that vendor. nOS hands over "the accounting specialization" instead:
plain files under an open licence, the data in the firm's own tables, staffed
by any model that passes Apgar (`tools/apgar.py`). A tissue is the unit an
outside tool (for example an end-user assistant) can be pointed at.

## 2. What a tissue is not

- **Not a new place to declare things.** A tissue lists ids that already
  exist in their own source. It defines no container, no table, no job, no
  prompt. If a part is missing, add it where that kind of part lives, then
  list it.
- **Not a plugin.** A plugin wires one service to the others. A tissue wires
  nothing; it names a set.
- **Not an organ or an organ system.** An organ is one service with one job;
  an organ system is the public grouping on the apex page. A tissue cuts
  across both: the backoffice tissue uses Dolibarr (organ) and the party
  tables (memory) and two invoice cells.
- **Not a model choice.** A tissue never pins a model. Which model staffs a
  cell is the cell's own binding (`agent.yml` `model:`), checked by Apgar.

## 3. The manifest

One file per tissue: `state/tissues/<name>.tissue.yml`, validated by
`state/genome/tissue.schema.json`. There is no third format: `meta:` is the
Tier-2 app manifest's own block (`state/schema/app.schema.json`, referenced,
not copied) plus a `license:`. The rest are lists of existing ids:

| key | id | resolves against |
|---|---|---|
| `cells` | agent name | `files/anatomy/agents/<id>/agent.yml` |
| `skills` | skill dir | `files/anatomy/skills/<id>/SKILL.md` (the shipped library; `.claude/` skills do not travel) |
| `tables` | table slug | `state/keap-tables/<id>.table.yml` |
| `services` | manifest id | `state/manifest.yml` row + `files/anatomy/plugins/<id>-base/plugin.yml` |
| `reflexes` | `<owner>:<job>` | a `pulse.jobs[]` row of `<owner>-base/plugin.yml` |
| `importers` | importer name | `state/digest-importers/<id>.importer.yml` |
| `seeds` | seed name | `state/fixtures/<id>.seed.yml` (reference data, no personal data) |
| `profile` | profile name | `profiles/<id>.yml` |
| `acceptance` | fixture name | `state/fixtures/<id>.seed.yml` + `<id>/expected.yml` + roadmap row `fixture-<id>` |

`tools/tissue-status.py` lists every tissue and resolves every id. One dangling
id refuses the whole tissue, and `tools/anatomy-graph-gen.py` will not compile
a graph that holds a refused tissue.

## 4. Article 30 is inherited, never written here

A tissue carries **no `gdpr:` block** (the schema refuses one). Its record of
processing is the set of blocks its members already declare: each cell's
`agent.yml`, each service's plugin, each reflex's owning plugin, each importer.
Every one of those must be complete by the Tier-2 rule
(`nos_app_parser.REQUIRED_GDPR`, a lawful basis from Art. 6(1)). A member
with a missing key refuses the tissue. Tables hold no block of their own; the
members that write them answer for them.

## 5. Install, remove, export

- **Install** is the profile: `nos -e @profiles/<profile>.yml` must switch on
  every service the tissue lists (by the profile or by the committed default).
  Tables, cells, skills and reflexes arrive with the converge that installs
  their organs. There is no separate installer.
- **Remove** goes through what exists. No per-tissue rung is on the ladder
  (`docs/nos-cli.md`); `nos --remove=` is estate-wide. Removing a tissue means
  the operator turns its services off in `config.yml` and converges. The firm's
  rows stay. Erasing them is a separate, explicit act
  (`tools/offboard-book-owner.py`, `tools/digest-teardown.py`, dry-run first).
  A member another tissue also lists (a shared table such as `party`) is never
  removed with one tissue.
- **Export / transplant** carries files: the manifest and every file it
  resolves to, under the licence in `meta`. It does not carry the firm's
  rows, credentials or `config.yml`. Rows travel only when the operator asks,
  as a digest bundle the receiving estate absorbs through its own gate.

## 6. Acceptance is a fixture

A tissue is accepted when a fixture passes through its cells. The fixture is
synthetic data already in the repo (seed + `expected.yml`) and a roadmap row.
The shape rule, checked offline: every table the fixture seeds is a table the
tissue holds. The effect (the fixture's invoices booked by the tissue's cells
and reflexes on a live estate) is `--tags verify` / e2e work and is not built.

## 7. Versioning

`meta.version` is the tissue's own semver. Adding a member is a minor bump;
removing or renaming one is a major bump. Members keep their own versions
(plugin `version:`, agent `version:`, the image pin in `default.config.yml`);
the tissue does not restate them.

## 8. The worked example: backoffice

`state/tissues/backoffice.tissue.yml` — every id checked against its source:

```yaml
meta: {name: backoffice, version: "0.1.0", license: MIT, category: business,
       summary: "Counterparties, invoices and double-entry books, with the desk that keeps them."}
cells:      [invoice-vision-ocr, invoice-extract]
skills:     [nos-backoffice, nos-datatables]
tables:     [party, party-tax-identity, party-address, party-contact, party-registry-status,
             account, invoice, invoice-line, invoice-review, pending-invoice-verify,
             journal-entry, posting, book-access, cnb-fx]
services:   [dolibarr, freescout]
reflexes:   [crm-hydrate:hydrate-parties, invoice-vision:intake-sweep, invoice-vision:absorb-approved]
importers:  [isdoc, isdoc-vision, doli-party, csv-party]
seeds:      [accounting]
profile:    praxis
acceptance: [consulting-firm]
```

Writing it found two gaps, now fixed at the source: the FreeScout and
invoice-vision plugins did not say whether data leaves the EU. Not yet
listable, because they have no id of their own: the n8n ARES and ČNB packs
(they live inside the n8n service) and the face Books app.

## 9. Gates

| rule | gate |
|---|---|
| the manifest has the schema's shape, no own `gdpr:` | `test_tissue_holds.py::test_every_tissue_holds`, `::test_a_tissue_cannot_declare_its_own_gdpr_or_an_unknown_key` |
| every id resolves; a dangling one refuses | `::test_a_dangling_reference_is_refused`, `anatomy-graph-gen.py --check` |
| Art. 30 inherited and complete | `::test_art30_is_inherited_from_every_processing_member` |
| the profile installs every service | `::test_the_profile_installs_every_service` |
| the fixture stays inside the tissue | `::test_the_acceptance_fixture_stays_inside_the_tissue` |
| a tissue is a graph node its members are part of | `::test_every_tissue_is_a_node_its_members_are_part_of` |
| the tissue level is not empty | `test_body_plan_is_a_projection.py::test_an_empty_level_is_counted_not_hidden` |
| removal never drops a shared member; export carries no rows | not built (no remove/export tool yet) |
