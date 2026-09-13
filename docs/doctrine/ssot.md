# SSOT — how to cite the constitution

> **PROPOSED, not settled.** This file names a citation scheme the tree already
> almost has (`tools/doctrine-cite.py`, `doctrine:<doc>#<section>`). It does not
> invent a second constitution store, a browser, or a parallel ontology. The
> operator settles this file before anything cites it as live. Sibling of
> [`agentkit.md`](agentkit.md) in status.

Unqualified `§N` is a defect. An agent said "paragraph eight" and the operator
could not find it: [`loops.md`](loops.md) §8 is an edge-gate rule;
`docs/workflow-standard.md` has two §9s (`Recursion` and `The checklist`);
[`../idea/08-lifecycle.md`](../idea/08-lifecycle.md) is a different file.

## 1. Citation form

`nos-sot:<realm>/<file>#<stable-id>` — e.g. `nos-sot:doctrine/loops.md#8`.

| realm | lives at | stable-id |
|---|---|---|
| `doctrine` | `docs/doctrine/*.md` | the `##` heading (its section number, when it has one) |
| `idea` | `docs/idea/*.md` | same |
| `genome` | `state/genome/` | schema path (`entity.schema.json`) |
| `dtt` | roadmap slugs | the slug (`dtt-constitution`) |
| `fee` | `docs/hidden_fees/NN-*.md` | the NN (`08`) |

A path outside those five realms is not a `nos-sot:` address. Cite it as a repo
path, or move it into a realm. `tools/doctrine-cite.py` already harvests `§`
citations and refuses to guess an unqualified one; `nos-sot:` is the qualified
form that harvest should grow to emit. Do not stand up a second resolver.

## 2. Constitution

The constitution is `docs/doctrine/*.md`. Each `##` heading is the stable-id;
[`loops.md`](loops.md) already claims section numbers stable. Renaming a number
is a breaking citation change.

The signed-row store is the queued roadmap row `nos-sot:dtt/dtt-constitution`
(constitution-as-dtt, deferred — `docs/plans/datatables-subsystem.md` §14). Do
not invent a second constitution table beside that row. These files stay the
source until it lands.

[`agentkit.md`](agentkit.md) §6 and [`organs.md`](organs.md) §3 await the
operator; this file does not settle them.

## 3. Genome

`state/genome/entity.schema.json` is the machine model. It has facets
(`identity`, `compliance`, `access`, `cortex`, `face`, `axes`) and almost no
instances: one organelle schema
(`state/genome/organelle/data-table.schema.json`). `tools/genome-codegen.py`
already emits the two live artifacts. Fill instances; do not open a second
schema family.

The identity hook is `identity.anchor` (renamed from `taxonomy_anchor` on
2026-08-07 after that name had zero producers and zero consumers). Re-measure
it. Do not invent a parallel ontology for doctrine nodes.

## 4. KEAP — one node per file

One KEAP node per doctrine file, not per sentence. Edges:

`doctrine --governs--> surface` (plugin / role / organ)

Blast radius is a graph walk, not a paragraph. Today's anatomy-graph doctrine
edges (`derive_doctrine` in `tools/anatomy-graph-gen.py`) are citation-derived
per-section addresses (`doctrine:<doc>#<section>`), walked `governed_by`
(surface → paragraph). That harvest stays a citation index; the KEAP node is
the file. Same join, coarser node, opposite walk — not a second graph.

## 5. One export, many faces

Wing and the face consume the same export KEAP nodes consume:
`tools/ssot-index.py` JSONL of `nos-sot:` rows. Named, not built. Do not draw a
browser from this file. Until that exporter exists,
`tools/doctrine-cite.py --json` is the harvest.

## 6. Heading uniqueness

Every ATX heading in a `docs/doctrine/*.md` file is unique inside that file —
the title text, and the section number when numbered. Gate:
`tests/anatomy/test_doctrine_headings_are_unique.py`. The citation indexer
(`index_doc`) last-write-wins on a repeated number, so a collision is silent
without this gate.

**Named collision, not in this realm:** `docs/workflow-standard.md` has two
`## 9` headings (`Recursion`, `The checklist`). Unqualified `§9` is why this
file exists. Not repaired here — it is not constitution, and inbound checklist
citations would churn. Cite it by title, or not as `nos-sot:`.
