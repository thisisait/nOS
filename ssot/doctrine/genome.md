---
in_force: false
ruled: null
row: body-plan-levels-complete
gates: []
---
# Genome — the declared facts every part inherits

> **PROPOSED** (2026-10-07, roadmap row `body-plan-levels-complete`). Not in
> force until the operator says so. It states only what has shipped; the
> history and the open promises stay in
> [`docs/idea/06-genome.md`](../../docs/idea/06-genome.md).

## 1. What the genome is

The genome is the set of declared facts every part of nOS inherits. Its bytes
live in `state/genome/` (the `genome` realm of `ssot/INDEX.yml`). It is not
law: law is the rules in force and lives in `ssot/doctrine/`.

## 2. What it holds today

- `lexicon.yml` — one meaning per word ([`body-plan.md`](body-plan.md) §1).
- `entity.schema.json` — the base entity. Its facets (`identity`,
  `compliance`, `access`, `cortex`, `face`, `axes`) are composed with `$ref`
  and `allOf`, so a fact is declared once and inherited.
- `genes/` — the entity kinds. Today there is one: `data-table`.
- `tissue.schema.json` — the shape of a tissue file ([`tissue.md`](tissue.md)).
- `task-types.yml` — the declared work contracts. A cell lists the ones it
  may take under `task_types:` in its `agent.yml`; `AGENTS.md` is rendered
  from this file.

One genome place is outside `state/genome/`: the skill library,
`files/anatomy/skills/`. A skill is a declared how-to a cell or a runtime is
handed, and it ships with the code that reads it, so it stays there.

## 3. A gene

A gene is one declared kind of entity that composes `entity.schema.json`.
A validator in `state/schema/` checks a file's shape; it is not a gene.

## 4. Generated, never typed

`tools/genome-codegen.py` turns the genome into the files each runtime reads:
`files/anatomy/module_utils/nos_entity.py`,
`files/anatomy/face/src/lib/contracts/entity.gen.ts` and
`docs/glossary.md`. Nobody edits those by hand. `--check` fails when one is
stale. Gates: `tests/anatomy/test_genome_contract.py`,
`tests/anatomy/test_genome_axes_facet.py`, `tests/anatomy/test_lexicon_holds.py`.

## 5. Facts, not capabilities

A fact about an entity is data: declared once, inherited, generated
everywhere. What may act on an entity is code, written per runtime. A
capability is never added by declaring it in the genome.

## 6. What it does not hold yet

The Wing and Cortex emitters do not exist; two of the generator's planned
targets are missing.
