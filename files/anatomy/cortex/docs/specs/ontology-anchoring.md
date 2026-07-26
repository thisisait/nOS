# Ontology anchoring — domain packs, decision logic, and the LLM context injector

> Vendored from thisisait/nos-keap @ v1.28.0 (94acbfe) docs/specs/ontology-anchoring.md — organ-side copy, P-4b Docs stage 2026-07-25. The KEAP original remains authoritative until the post-C4 docs cleanup.

Status: **design.** Written 2026-07-22 against v1.23.0. Owner intent (verbatim,
condensed): the taxonomy-ontological substrate must be able to record *business
logic — of anything, up to the whole world* — and serve it back as (a) an
in-the-box decision aid, (b) a knowledge base, (c) an **LLM context injector**.
Standing target use case: one constellation = the *entire legislation and case
law of a state*.

This spec does not invent a new substrate. It names the one we already have,
declares it the anchoring contract, and works out what breaks at each order of
magnitude — so every future domain (an org's business logic, a legal corpus, a
scientific field) lands the same way the nOS self-model did.

## 1. The four-layer anchoring model (all four already exist)

| layer | carrier | what it records | today |
| --- | --- | --- | --- |
| **Skeleton** | taxonomy: seed domains + slug user roots (`nos`, …) | the *concept hierarchy* of a domain | v1.19–v1.21: user roots, own ring, boot fixpoint |
| **Evidence** | knowledge objects (cards, fs mirrors, tables) | the *texts/data* a concept is grounded in | fs-sync, mapped folders, OKF cards |
| **Assertions** | R3 typed relations (`relation_types` registry) | *what relates to what, and how* (verbs, confidence, provenance) | v1.16+: moderated typed edges |
| **Rules** | R4 conditional relations (reified edges) | *when an assertion holds* — the business logic | specced (`conditional-relations.md`), not built |

The doctrine that falls out of the table:

- **Concepts live in the skeleton, never in cards.** A card *grounds* a concept
  (anchors, `[[refs]]`); it never substitutes for one. If a domain needs a
  concept the tree lacks, the tree grows (Track T) — the card does not become a
  pseudo-node.
- **Logic lives in edges, never in prose.** "Driving requires a licence" is an
  R4 conditional edge between two R3 edges — queryable, moderatable, citable.
  The same sentence inside a card is *evidence for* that edge, not the edge.
- **Concept level, not instance level** (R4 doctrine, restated as the outer
  boundary): KEAP records that *a citizen* needs a licence, never whether
  *Pázny* holds one. Operational/personal state belongs to the services, not
  the concept graph. This is what keeps "the whole world" tractable: the world
  of *rules and concepts* is millions of nodes; the world of *instances* is not
  ours to hold.

## 2. Domain packs — the unit of "anchoring a world"

A **domain pack** is the deliverable that plants one domain. It is exactly the
shape the nOS self-model already ships (contract v1, golden fixture accepted in
v1.23.0), generalised:

```
pack = {
  root:      one slug user root            e.g. `law-cz`
  skeleton:  canonical domain files        law-cz.json, law-cz.civil.json, …
  cards:     one card per grounding text   fs-synced tree or OKF ingest
  relations: R3 seed edges + R4 rules      cites / amends / requires / conditioned-on
  fixture:   golden consumer fixture       the pack's acceptance gate
}
```

Contract points (all proven by the self-model chain):

1. **Slug ids are identity, position is not** (v1.20 lesson). `law-cz.civil.89`
   survives renumbering of siblings; a legal amendment that moves a section
   changes its *name*, not its id → identity-drift detection applies as-is.
2. **Boot-fixpoint registration** (v1.21 lesson) — a pack is a whole subtree
   arriving at once; ingest order must never drop it. Already hardened.
3. **The fixture is the gate.** A pack ships with a golden fixture + recall
   gate run; a pack whose fixture cannot pass the consumer gate does not pin.
4. **Visibility is a pack property.** `KEAP_FS_SHARED_UIDS` made the self-model
   readable by every tenant user; packs declare shared vs. private the same way.

### The legislation constellation, concretely

- L0 root `law-cz` (constellation), L1 = code/act (`law-cz.civil`), L2 = part,
  L3+ = free-zone depth down to section clusters. Sections themselves are
  **cards** (evidence layer), not taxonomy nodes — a statute's *text* is
  evidence; its *structure* is skeleton. This caps skeleton size at ~10⁴ for a
  state while cards carry the ~10⁵–10⁶ texts.
- R3 verbs the legal domain needs: `cites`, `amends`, `repeals`, `implements`
  (EU→national), `interprets` (judikatura→section). All entity-scoped.
- R4 carries the actual legal logic: *(citizen —performs→ driving)
  —conditioned-on→ (citizen —holds→ licence)*. Case law cards attach as
  evidence on the R4 edge (provenance), which is precisely what a lawyer asks
  for: the rule, its exceptions, and who said so.

## 3. Scale tiers — what breaks between 10³ and 10⁶

Today `/api/graph` ships the whole scene and the client renders it (U2″ LOD
handles *drawing* at ~20k bodies). The legislation constellation breaks the
*payload*, not the renderer. Three declared tiers:

| tier | corpus | payload strategy | render strategy |
| --- | --- | --- | --- |
| **S** (today) | ≤ ~5k objects | full graph payload | U2″ LOD as shipped |
| **M** | ≤ ~50k | `/api/graph` ships skeleton + **aggregates** (per-hub counts/hues); object bodies fetched per region (`?under=<node>`) on approach/expand | instancing everywhere; nebula impostors from server aggregates, not client passes |
| **L** | ≤ ~10⁶ | region streaming + server-side centroid/extent bake (a `layout_aggregates` sibling of `taxonomy_layout`); embeddings sampled/partitioned per pack | constellation renders from aggregates only; bodies exist client-side solely inside the focused region |

Rules that keep the tiers honest:

- **Spatial memory scales by construction**: aggregate positions derive from
  the same deterministic bake, so tier changes never move a star.
- **The core view is a projection, not a copy** (v1.24 lesson: user-root
  constellations relocate into the core *client-side only*). At tier M/L the
  projection must be computable from aggregates alone.
- **No silent truncation**: a payload that dropped bodies says so
  (`meta.tier`, per-hub `total` vs `shipped`) — the "corpus exhausted" class of
  lie is the one we always regret.

## 4. The context injector — `/agent/v1/context`

The consumer surface that makes the graph *useful in the box*. One endpoint,
deterministic assembly, budget-bounded:

```
POST /agent/v1/context   { query: string, budget_tokens?: number,
                           roots?: string[], depth?: 'facts'|'rules'|'full' }
→ {
    focus:      resolved concepts (taxonomy hits, with paths)
    rules:      R3/R4 edges touching the focus, verb + confidence + condition chains
    evidence:   top cards (recall-gate-ranked), each with a stable citation id
    provenance: per item — pack, source path/url, moderation state
    budget:     { requested, spent, dropped: {rules: n, evidence: n} }
  }
```

Design commitments:

1. **Assembly order is rules-first.** A decision question wants the R4 chain
   (rule → conditions → exceptions) before prose; evidence fills the remaining
   budget. `depth=facts` skips rules for cheap lookups.
2. **Ranked by the recall gate's measure.** The gate (v1.22) is the *proof*
   that semantic retrieval means something; the injector uses the identical
   retrieval path, so gate green ⇒ injector trustworthy. A pack's fixture adds
   domain queries to the gate.
3. **Citable or absent.** Every returned item carries a stable id
   (`law-cz.civil.89`, `obj:…`, relation id) — an LLM consumer can quote it,
   and a human can click through to the star. No anonymous snippets.
4. **Confidence is forwarded, never flattened.** Proposed (unmoderated) edges
   are excluded by default, included under an explicit flag — the injector must
   not launder a classifier guess into "the law says".
5. Surfaced to agents as an MCP tool / AgentKit skill (`keap-context`), the
   same way skills already mirror into the self-model.

## 5. Sequencing

1. **R4 conditional relations** (`conditional-relations.md`) — the rules layer
   is the prerequisite for everything "decision". Unblocks: injector `rules`.
2. **`/agent/v1/context` v1** at tier S — rules-first assembly over the
   existing corpus + recall-gate ranking. Small, provable, immediately useful
   to the nOS agents.
3. **Domain-pack contract v1** — generalise the self-model pipeline (root +
   canonical files + fixture + gate) into a documented, second consumer.
   Candidate first pack: a small real one (e.g. one Czech act + 50 sections)
   to force the card/skeleton split decisions while tier S still holds.
4. **Tier M payload** (aggregates + region fetch) — required before any pack
   crosses ~5k cards; the legislation constellation waits on this.
5. **Tier L** — only when a real 10⁵+ pack is committed. Do not build ahead.

## 6. Explicit non-goals

- No instance-level data (people, cases-in-progress, account state) — the R4
  concept/instance boundary is the product's privacy line, not a limitation.
- No general rules engine / inference chains beyond R4's one-hop conditions
  until a consumer proves the need — a rule you cannot moderate is a liability.
- No per-domain bespoke schemas: if a pack cannot express itself in
  skeleton/evidence/assertions/rules, the *model* gets the discussion, not a
  side channel.
