# KEAP semantic lens over the star-map

**Status:** PoC VALIDATED (2026-07-14). The difference-vector semantic axes produce
clean, interpretable signal on the real 1462-node embedding corpus — see the
results table below. Next: productionise the derived-features job + GraphCanvas
rendering. Roadmap item: `docs/roadmap.md` (KEAP section).

## Idea
Every node carries a 768-dim embedding (`nomic-embed-text`, local Ollama, synced by
`keap-embed-sync` into the libSQL `embeddings` table). The **U1 star positions are
structural** (the taxonomy tree, baked, append-only) and must NOT move. But the
*appearance* channels — colour, size, texture, rotation — are free, and embeddings
can drive them so the map becomes a **semantic heatmap** without breaking U1.

## PoC result (validated, `tmp/semantic-axes-poc.py`)
Semantic axes derived as **difference vectors** between exemplar poles
(`axis = normalize(mean(embed(positive)) − mean(embed(negative)))`), then every
node's unit embedding projected onto the axis (`score = node · axis`). The axes are
strikingly clean:

| axis | top (positive pole) | bottom (negative pole) |
|------|--------------------|-----------------------|
| **abstractness** | Formal Sciences, Abstract Algebra, Commutative Algebra | Practical Skills, Small Engines, Plumbing |
| **scale** (macro>micro) | Cosmology, Galactic/Stellar Astronomy, Astrophysics | 2D Materials, Quantum Chemistry, Cryo-EM, NMR |
| **formal** (vs empirical) | Mathematical Logic, Proof Theory, Model/Set Theory | Demography, Econometrics, Spectroscopy |
| **dynamic** (vs static) | Dance, Relative motion, Chemical Kinetics | static structures |

Plus **centrality** = mean cosine similarity to the corpus (hub-ness) → size channel.
The validated exemplar phrase-sets live in the PoC script (multi-phrase per pole,
averaged for robustness).

**Phase-3 compute core also validated** (`tools/keap-semantic-lens/compute-features.py`):
the full per-node feature set — 4 axis projections + centrality + a numpy k-means
(k=12) cluster id — computed over the live corpus. The clusters are strikingly
coherent semantic facets (ready for the texture channel): c4 fundamental physics
(QFT/QM/Classical), c7 philosophy (Metaphysics/Ontology/Logic), c9 computer science,
c10 mathematics, c1 biology, c5 arts, c0 the string-theory/quantum-gravity cluster,
etc. Output shape: `{id, abstractness, scale, formalness, dynamism, centrality,
cluster}` — a handful of scalars per node, exactly what the render path needs.

## Architecture — the trust-split-clean version
Embeddings live in the container; Ollama is host-loopback-only (the container on
`gated_net` cannot reach it — same split as `keap-embed-sync`). Two moving parts:

1. **Host: embed the exemplars.** ~20 short phrases → Ollama → 4 (or N) axis vectors
   (768-dim each, tiny). The exemplar sets are config (a committed YAML/JSON), so the
   axes are reproducible + versioned, not ad-hoc.
2. **Container: project + store.** Given the axis vectors (POSTed in) it computes, for
   every taxonomy embedding: the projection scalar per axis + centrality (mean cosine
   to corpus, or embedding norm) + optional k-means cluster id (texture facet). Stores
   a few scalars per node — NOT the 768-dim vector — in a `node_features` table
   (`node_id, abstractness, scale, formalness, dynamism, centrality, cluster`,
   `features_hash` to skip unchanged). Keeping the heavy 1462×768 projection in the
   container (next to the data) means only ~4 axis vectors cross the boundary.

An offline job (sibling of `keap-embed-sync`, a Pulse job) orchestrates: embed
exemplars host-side → POST axis vectors to a new `/agent/v1/features/recompute`
endpoint → container computes + upserts `node_features`. Idempotent; re-runs after
`keap-embed-sync` so features track description edits.

## Rendering — GraphCanvas "semantic lens" toggle
The `/api/graph` payload gains an optional `features` block (the per-node scalars).
`GraphCanvas` maps them to channels behind a **"semantic lens on/off"** toggle
(analogous to the existing relations toggle), a few scalars per node, never 768-dim
in the renderer:
- **hue** → projection on a chosen axis (a diverging gradient; a dropdown picks which
  axis, or blends two axes into a 2D colour field).
- **size** → centrality (hubs bigger) — or embedding norm.
- **texture / material** → k-means cluster (categorical facet).
- **rotation / orientation** → embedding direction vs the chosen axis (a node "points"
  toward abstract/concrete).
Positions stay tree-baked — the lens only re-skins the existing stars.

## Stability
Fixed-exemplar axes are stable (the exemplars are constant config); a rewritten
description shifts that node's embedding → its colour/size move a little, which is
correct (it says the meaning changed). This beats PCA/UMAP, which recompute the whole
projection basis whenever the corpus changes (every node's colour jumps). The
`features_hash` + re-run-with-embed-sync keeps drift bounded.

## Phases
1. **PoC** ✅ — difference-vector axes validated on the live corpus.
2. **Exemplar config** ✅ — `tools/keap-semantic-lens/axes.json` (versioned phrase-sets).
3. **`node_features` table + pipeline endpoints** ✅ — `server/db.ts` table +
   `readTaxonomyVectors`/`upsertNodeFeatures`/`getNodeFeatures`; `GET /agent/v1/
   features/vectors` (bulk export) + `POST /agent/v1/features` (upsert); `/api/graph`
   node payload gains a `features` block. Server TS typechecks clean.
4. **Offline Pulse job** ✅ — `files/anatomy/scripts/keap-features-sync.py`
   (host: fetch vectors → embed exemplars via Ollama → project + centrality + k-means
   → POST). Registered in `keap-base/plugin.yml` at 05:00 (after embed-sync, before
   lint). Reuses the validated numpy compute (Option B).
5. **GraphCanvas semantic-lens** — render logic ✅ (`nodeColor`/`nodeSize` gained a
   backward-compatible `lens?: LensState` param: colour by axis projection, size by
   centrality; dormant until wired). **Remaining (needs the running app to tune
   visually):** (a) thread a `lens` state into the ForceGraph3D `nodeColor`/`nodeVal`
   accessors; (b) ensure the API→CanvasNode mapping carries `features`; (c) a
   SidePanel toggle + axis picker + legend; (d) optional texture=cluster / rotation
   channels. All the data (embeddings→features→payload) is in place; this is UI wiring.

**Activation:** nothing runs until the next keap rebuild (new image ships the endpoints
+ table) and `keap-embed-sync` populates embeddings for the freshly-added content
(physics/L0/bio/chem/earth/math), after which `keap-features-sync` fills `node_features`.

## Guardrails
- Embeddings drive **appearance only** — never position (U1 baked layout is inviolate).
- Store scalars, not vectors, in the render path.
- Exemplar axes are versioned config so the semantic space is reproducible.
- Recompute after `keap-embed-sync` (features follow the corpus).
