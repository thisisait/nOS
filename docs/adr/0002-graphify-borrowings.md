# ADR-0002 — Graphify borrowings: code graph, communities, merge driver, and what embeddings may not be

- **Status:** Decided 2026-09-02 (items 3–5); the embeddings doctrine (§4) is a
  **recommendation awaiting the operator** — it reaches KEAP's
  `keap-embed-sync` and Qdrant, so it is not this ADR's to settle.
- **Context:** roadmap row `cortex-graph-borrowings`. The same-day work already
  landed `evidence` on every graph edge and `tools/graph-report.py`; this ADR
  records the three remaining decisions the row required *before any code*.
- **Scope:** the anatomy graph (`state/anatomy-graph.json`, 256 nodes /
  286 edges) and the retrieval surfaces of the cortex organ. Nothing here
  changes retrieval behaviour.

---

## 1. Item 3 — the code graph (decided: defer vendoring; three answers recorded)

The estate has an infrastructure graph and a concept graph and nothing that
answers *what calls `nos_prune_plan`*. Graphify (Apache-2.0, tree-sitter,
deterministic, no LLM) is the right shape — a detector that reads the artifact.
The three questions the row required answered before vendoring:

1. **Where it lives: a FOURTH artifact** (`state/code-graph.json`), never edges
   in `anatomy-graph.json`. The grains differ by two orders of magnitude
   (256 estate nodes vs thousands of symbols), the regeneration cadence differs
   (manifest edits vs every code edit), and drowning the estate graph would
   break every reader shipped today. The two link by node id convention
   (`code:<path>:<symbol>` may cite `service:*` nodes), not by cohabitation.
2. **Who regenerates it: the committer, enforced by the regenerate-and-diff
   gate** — the same pattern that already pins `anatomy-graph.json`
   (`test_the_committed_graph_matches_a_fresh_build`). No pulse job, no daemon:
   a code graph is stale the moment code changes, so the only honest trigger is
   the change itself, and CI refusing drift is the enforcement that exists.
3. **Dev tool only, never a role.** Every consumer named by the row (surveyor,
   upgrade-architect, SERE) runs host-side and can read a committed artifact.
   A role would put a Python extractor into the runtime estate with zero
   runtime consumers — a service without a caller, which is what the isolated
   node report exists to catch.

**Vendoring is DEFERRED, with the reason stated:** no consumer today asks a
code-graph question. The first concrete query wired into surveyor or
upgrade-architect is the trigger to vendor; vendoring ahead of it would be a
fourth artifact nothing reads, i.e. motion that looks like correctness.

## 2. Item 4 — communities as a cross-check (decided: stdlib, no networkx; the disagreement, measured)

**No `networkx`.** Measured before deciding: the linked graph is 191 nodes /
286 edges; deterministic label propagation (sorted visit order, min-label
ties) converges in a handful of sweeps and answers the only question asked —
*where does the wiring disagree with the declared axes*. Leiden's advantages
(resolution parameter, guaranteed well-connected communities) buy nothing at
this size that changes a disagreement report. `tools/graph-communities.py` is
the reader; gate `tests/anatomy/test_graph_communities_reader.py`.

**The disagreement — which is the deliverable (2026-09-02):**

- **Naive run: communities measure "who Authentik gates", not any declared
  axis.** One community of 96 anchored on `service:authentik` holds services
  from all 8 stacks. The SSO vein is the estate's strongest structural signal —
  stronger than `stack`, `layer`, or kind.
- **With the hub dropped (`--drop=service:authentik`): `stack` is not recovered
  anywhere.** 33 communities; `iiab` shatters into 15, `devops` into 5 (each
  devops service lands in a different community). The declared `stack` axis is
  a *compose-project grouping*; the wiring axis is orthogonal to it.
- **What the wiring actually clusters by is SUBSTRATE and VEIN:** the largest
  mixed community (23 members, b2b+infra+iiab+voip+data) is exactly "everything
  that depends on MariaDB/Redis" — 25 internal edges, all `kind: data`.
  Another is "who ships a Grafana dashboard". So a community straddling stacks
  is not a mislabeled service; it is a shared substrate, which is what
  `layer` (blast radius) was invented to express and `stack` never claimed to.
- **Verdict:** the axes disagree *by design*, and the cross-check's value is
  negative evidence — nobody may derive `stack` from the graph (precedent:
  `plat-defaults-derive` falsified the derived-defaults rule the same way).
  `layer` remains the axis the wiring can inform; 40 nodes still carry
  `layer_withheld` and the survey, not the clustering, is how they get a value.

## 3. Item 5 — merge driver for derived state artifacts (decided: `merge=regen`, keep-ours + regenerate)

`.gitattributes` marks the two copies of the derived graph artifact
(`state/anatomy-graph.json`, the face vendored copy) with `merge=regen`.
Semantics, proven on a synthetic three-way conflict before shipping:

- driver configured (`git config merge.regen.driver true`, one-time setup in
  the same class as the pre-push hook): merge keeps OURS cleanly — correct,
  because *any* content resolution is wrong until the generator reruns, and
  `test_the_committed_graph_matches_a_fresh_build` already refuses a stale
  artifact in CI. Keep-ours + regenerate is the documented resolution.
- driver NOT configured (fresh clone): git falls back to a text merge — a loud
  conflict, still resolved by regenerating. Fail-loud, never silent.

Deliberately NOT `state/*.json`: `night-watch.json` is *authored* expectations,
not a derived artifact — regenerate-on-conflict does not apply to it, and a
text merge there is the right behaviour. The attribute is scoped to artifacts a
generator owns. Gate: `tests/anatomy/test_state_merge_driver.py`
(asks `git check-attr`, the artifact, not this prose).

## 4. The embeddings question — state of play, measured; recommendation for the operator

**Do not assume; the callers were counted (2026-09-02, vendored organ
`files/anatomy/cortex/`):**

- **The resolver path can say NOTHING.** `cortex-resolve.ts` (BM25/FTS +
  ambiguity margin, sole caller `cortex-validate.ts` ← `POST
  /agent/v1/validate`) returns `unknown_operand` / `ambiguous_operand` — real
  negatives with candidates. It already refuses RRF-derived thresholds
  (adjacent RRF ranks differ by ~0.00026; a floor built on it fires always or
  never). Zero embeddings involved.
- **The ANN path cannot say NOTHING, and today nothing asks it.**
  `db.ts::vectorNeighborsOf` is pure top-k (`vector_top_k` → `ORDER BY
  distance ASC` → slice) with **no distance floor**; the cosine distance is
  computed, returned, and then discarded by the one caller —
  `search.ts::hybridSearch` folds it into RRF rank. And `hybridSearch` itself
  has **zero route callers in the organ**: `index.ts` serves no search route
  and says so ("this organ does not serve semantic search"). The organ's
  vector corpus is *write-only* today — `keap-embed-sync` (04:45 nightly)
  feeds `POST /agent/v1/embeddings`, `cortex-ann.ts` tunes the index at store
  open, and no query reaches it. The only "nothing" the vector leg can report
  is *unavailable* (`embedText` → null when no embedder is wired), never
  *no confident match*.
- **Qdrant is a substrate with zero consumers.** Bone proxies
  `/api/v1/embeddings/{upsert,search}` (503 when unconfigured);
  `install_qdrant` defaults false; apex ruled `service:qdrant` WITHHELD; no
  production code calls Bone's search route (only docs, the OpenAPI contract,
  and its own gate).

**Recommendation (operator's call, not shipped):** adopt the row's proposed
doctrine — *embeddings are a RESOLVER at the boundary (text → node id), never a
STORE of relations*. Concretely, if/when a question is routed to the ANN path:

1. the path must first gain a declared **distance floor** so it can return
   *no confident match* — the raw cosine distance is already computed and
   discarded, so the floor is a decision, not new machinery; calibrate it on
   the live corpus the way the RRF refusal was calibrated (measure the
   distance distribution, then declare);
2. an ANN hit resolves to an id and every subsequent question is a graph/FTS
   question with provenance — a float is not evidence;
3. until a consumer exists, **build no third retrieval surface**: the honest
   description of today is FTS answers questions, vectors are ingested nightly
   and asked nothing, Qdrant is withheld. Rot note: a `measured` edge rots
   detectably (graph-report proves it); a vector has no date to compare — the
   nightly re-embed via content-hash diff is what stands in for rot detection,
   and it covers only the libSQL corpus, not Qdrant.

No retrieval change ships with this ADR.
