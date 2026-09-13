# SSOT — how to cite the constitution

> **PROPOSED, not settled.** This file names the citation scheme and the
> destination shape of a law. It does not invent a second constitution store,
> a browser, or a parallel ontology. The operator settles this file before
> anything cites it as live. Sibling of [`agentkit.md`](agentkit.md) in status.

## 1. Address

A citable unit has one address: `nos-sot:<realm>/<file>#<id>`.
A section number without a realm and a file is not an address.

## 2. Realms

| realm | corpus | id |
|---|---|---|
| `doctrine` | `docs/doctrine/*.md` | the `##` heading's section number, else the heading slug |
| `idea` | `docs/idea/*.md` | same |
| `genome` | `state/genome/` | schema path (`entity.schema.json`) |
| `dtt` | roadmap slugs | the slug (`dtt-constitution`) |
| `fee` | `docs/hidden_fees/NN-*.md` | the NN (`08`) |

Organs are not a sixth realm. [`organs.md`](organs.md) is doctrine: the rule
for the word. The organ *vocabulary* belongs in the genome, the same way
`axes.layer` already does, once the operator settles organs.md §3.

A path outside these realms is a repository path, not a `nos-sot:` address.
`tools/doctrine-cite.py` is the harvest. `nos-sot:` is the qualified form it
should emit. Do not stand up a second resolver.

## 3. Constitution

The constitution is `docs/doctrine/*.md`. Each `##` heading is the id.
Changing a number is a breaking citation change.

An article is a norm (`shall` / `must` / `may` / `must not`). Incidents,
measurements, and named exceptions live in a companion, a fee, or the
devlog — not in the article.

The signed-row store is queued as `nos-sot:dtt/dtt-constitution`. These files
stay the source until that row lands. Do not invent a second constitution
table.

[`agentkit.md`](agentkit.md) §6 and [`organs.md`](organs.md) §3 await the
operator. This file does not settle them.

## 4. Genome

`state/genome/entity.schema.json` is the machine model. Fill instances. Do
not open a second schema family.

The identity hook is `identity.anchor`. Re-measure it. Do not invent a
parallel ontology for doctrine nodes.

## 5. Format

A law that defines a paragraph is one article: stable id, normative text,
in-force range, optional amendment or repeal of another id.

Authoring stays Markdown until a genome article schema exists. JSONL and XML
are projections of that schema, not a second source. XML is a candidate
because amendments need identity and supersession — not because the corpus
should be hand-written as tags.

One article = one vector chunk. One doctrine file = one KEAP node. Blast
radius is the walk `doctrine --governs--> surface`. Do not mint a KEAP node
per sentence.

Tenant constitutions reuse the article schema and the unique-name rule.
They do not inherit this estate's articles. Their prefix is not `nos-sot:`.

## 6. Export

Wing, the face, and KEAP consume one export: `tools/ssot-index.py` JSONL of
`nos-sot:` rows. Named, not built. Until it exists,
`tools/doctrine-cite.py --json` is the harvest.

## 7. Heading uniqueness

Every ATX heading in `docs/doctrine/*.md` is unique inside its file — the
title text, and the section number when numbered. Gate:
`tests/anatomy/test_doctrine_headings_are_unique.py`.

A duplicate number outside doctrine is not a `nos-sot:` address.
