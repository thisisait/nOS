# 03 — The corpus, and what it can honestly recall

**Status: the agreement harness is live and measured nightly. The corpus itself
is thin by INPUT, not by design — and that is the finding that reorders
everything downstream.**
**Detail:** [`cortex-self-core.md`](../archive/cortex-self-core.md) ·
[`cortex-corpus-parallel.md`](../archive/cortex-corpus-parallel.md) ·
[`nos-cortex-organ-design.md`](../archive/nos-cortex-organ-design.md) ·
[`cortex-docs-schema.md`](../archive/cortex-docs-schema.md) ·
[`cortex-s3-s4-workflow-set.md`](../archive/cortex-s3-s4-workflow-set.md)

## Where it stands, measured

From `~/.nos/cortex-corpus-diff.json`, the nightly ledger, on 2026-08-02:

```
result agree · agreeStreak 6 · all six clauses true
taxonomy_nodes        2500 / 2500   (0 on either side alone)
knowledge_objects[fs:] 317 /  317
relations             1438 / 1438
```

KEAP and the vendored organ agree. Asymmetries are **named** rather than counted
as drift: the estate's own 1 088 doc nodes, the 97 nodes outside the referee's
jurisdiction, the KEAP-only table cards.

## The organ

`pazny.cortex` is the fourth host organ beside Bone, Wing and Pulse — *Cortex
remembers and reasons*. A loopback daemon on `127.0.0.1:8098`, a verbatim TS/Node
port vendored under `files/anatomy/cortex/`, owning one libsql store with the ANN
index tuned to the measured optimum (float8, `max_neighbors=20`).

Being a host process reading a host-local store is not incidental: it **dissolves
the Wing-executor network risk** (launchd→launchd loopback, no host→container
hop) and colocates the recall gate with the host Ollama embedder, where they are
architecturally forced to live.

## The finding that reorders the roadmap

**The user tree measures at ONE real document.** There is no ZIM reader and no
Calibre/EPUB reader at all — Kiwix and Calibre are deep-linked, never read.

So every proposal to improve *extraction* optimises the second bottleneck. The
`ai-knowledge-graph` audit reached the same conclusion independently. The order
is:

1. **ZIM/EPUB readers** — give the corpus something to read.
2. **Finish the curator's P1 relation path** — the ANN substrate is already live
   at recall@10 = 100 %, so it is `POST /agent/v1/relations` plus a prompt.
3. **Only then** weigh a heavier extractor (`getzep/graphiti`) against its
   Neo4j/FalkorDB cost.

## The discipline that already exists, and is worth defending

The curator's cross-domain weaver picks candidates by embedding similarity across
a domain boundary, **forces one of the 16 typed predicates**, floors confidence
at 0.7, caps at 15 per run, and lands in a `promotions` queue where nothing
auto-applies.

Compare the audited alternative, whose *default* config invents edges to connect
disconnected components and merges entities on a 4-character prefix. Pointed at a
curated ontology that is a corruption mechanism, not an extractor. **The
discipline is the asset; the extractor is replaceable.**

## Open

- `syncRows()` — rows as first-class objects. Ratified `D3 = materialised`,
  `graphMetaSchema` already accepts `mode: 'rows'`. Not built.
- Recall beyond the fs corpus: `realUserDocs = 28` against 2 500 taxonomy nodes.
- The corpus-diff harness folds `table-*` rows into one counted line before
  `syncRows` lands, or 500 rows means 500 benign findings.
