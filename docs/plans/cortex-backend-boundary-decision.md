# Decision: cortex backend/UI boundary → Option D

> **Supersedes** the Option-C lean in `cortex-backend-boundary-rfc.md`.
> Resolves the RFC against the KEAP agent's ground-truthed reply
> (`knowledge-explorer-and-preserver` `feat/cortex-validate:docs/specs/cortex-backend-boundary-reply.md`, 660d84e).
> **Direction agreed; scope is an epic — the operator confirms the commitment (§6).**

## 1. The reply's decisive facts (measured, not estimated)

1. **The store is 17 MB of data in a 496 MB coat.** `keap.db` = 4.2 MB reasoning
   (8 tables) + 12.8 MB shared + **496 MB regenerable ANN/FTS index** + 0.3 MB UI
   state. The reasoning payload copies in a second; the index is derived and is
   ~50× oversized (default `libsql_vector_idx` params — 514 MB for 3 356 vectors;
   tunable to 41–66 MB, embed 48 s→6 s). A port is the moment to fix it.
2. **BLOCKER — 43% of the ontology is not data.** The 790-node **seed spine** is
   hardcoded in `src/game/data/taxonomy.ts` (3 452 lines) and imported by
   `server/taxonomy.ts` from the *frontend source tree*. Live: 1 841 nodes = 790
   seed (TS) + 1 051 grown (DB/git delta). git `knowledge/` is the SoT for the
   **delta only**. So "materialize from git" (Option C) yields a tree missing 43%
   of nodes — every L0/L1 the grown nodes hang from.
3. **Moving `validate` breaks no UI** — the KEAP frontend makes **zero** calls to
   `/agent/v1/*`; the UI talks to `/api/*` (80 routes). Agent surface and UI are
   already disjoint.
4. **The recall gate belongs in nOS anyway** — it needs a live embedder, which is
   host-Ollama (Pulse runs the embed sync; KEAP never reaches an embedder itself).

## 2. Why Option C is dead

C (each side materializes the git SoT into its own store) = **A plus duplication**:
two ingest implementations (two chances for the `onto1:` fingerprint to diverge →
the AST binding becomes decorative), two ANN indexes / two embed passes / two recall
gates, and it **still leaves KEAP running a backend** to render. It pays B's
migration cost and keeps A's backend. Rejected.

## 3. The real line is cortex-vs-product, not backend-vs-UI

"celý backend na nOS" read literally would move `fs-sync` and the face's DataTables
into the anatomy, which serves nobody. The line that matches the *intent*:

- **Cortex → moves to nOS:** `validate`, `validate/opcodes`, `taxonomy/search`,
  `taxonomy/node/:id`, `graph`, `relations`, `relations/candidates`,
  `search/semantic`, `embeddings*`, `features*`, + the planned `context`.
- **KEAP product backend → stays (not reasoning):** `fs/status`, `fs/sync`,
  `tables*` (the nOS face's DataTables), `captures`, `metadata`, `objects*`,
  `content/*`, `curator/*`, `lint*`, `promotions`, `topics*`.

KEAP legitimately keeps a backend — the one serving *its own product surfaces*.
`taxonomy_layout` (the spatial bake) + topic clusters are UI state but are
deterministic functions of the tree: whoever holds the tree bakes them; they don't travel.

## 4. Decision — Option D: one store in nOS, spine promoted to data first

**D is B done in the right order.** Phases:

1. **Promote the spine to data (prerequisite, KEAP-side).** Move the 790-node spine
   out of `src/game/data/taxonomy.ts` into `knowledge/canonical/`; `server/taxonomy.ts`
   reads it as data, not a frontend import. Independently worth doing: it makes the
   git SoT complete for the first time and brings the seed nodes under the same lint +
   round-trip gate the grown ones already pass. **Nothing ports until this lands.**
2. **Write the composition contract + a conformance fixture (prerequisite, joint).**
   `ast.binding.ontologyVersion` = `onto1:<sha256-16>` over the *composed* `allNodes()`
   — seed + ext, after the boot fixpoint (`registerExtNodes` drops parent-unresolved
   nodes), the zone/depth finalize, and K1 override layering. Two implementations that
   compose in a different order produce **different fingerprints from identical input**
   → every cross-checked AST rejected while both believe they're right. So the
   composition must become a **normative spec + a conformance fixture** (a canonical
   input tree and the exact `onto1:` it must yield) — a pass/fail target for the port.
3. **Stand up the cortex backend in the nOS anatomy** over the reasoning tables
   (4.2 MB) + shared block, rebuilding the ANN index there with tuned params, gated by
   `recall-gate.mjs` before/after (the gate moves to nOS with the embedder it needs).
4. **Port `validate` — with its test suite** (215 unit + e2e). The suite encodes the
   decisions (D1 scope model, late-binding, mandatory ambiguity rejection, the binding
   stamps), not just behaviour. Port, don't rewrite.
5. **KEAP re-points its UI at the nOS cortex API** and keeps its product backend
   (fs-sync, DataTables, captures, curator, lint) + UI-only state.

**Nothing is thrown away:** `feat/cortex-validate` runs wherever we decide, and it is
the executable spec for the ported backend. The executor PR-1 proceeds against
whichever `validate` is live at build time — and under D its phase-2 ↔ KEAP's phase-1
stop being a cross-team contract, so three of the executor's §8 questions dissolve.

## 5. Ownership after D

| surface | owner |
|---|---|
| cortex runtime — `validate`/`context`/`resolve`/executor/corpus/local-model + the ontology runtime store + ANN + recall gate | **nOS anatomy** |
| ontology + canonical **SoT** (incl. the promoted spine) | **git `knowledge/`** — shared, KEAP-authored via its curation UI |
| the composition contract + conformance fixture | **joint** (spec in git, both sides conform) |
| explorer / graph / review-queue / decision-tree UI + product backend (fs-sync, DataTables, captures, curator, lint) | **KEAP** |

## 6. The one operator decision

- **Option D** (recommended, matches the directive): the migration above. A real epic
  — a KEAP-side spine promotion + composition spec, then an nOS-side cortex-backend
  standup + `validate` port. Achieves "celý backend na nOS" honestly.
- **Option A** (minimal fallback): keep the cortex backend in KEAP; redefine the
  directive as *"nOS owns execution, credentials and the corpus; KEAP keeps the cortex
  backend."* Coherent, zero migration, but the reasoning backend stays in KEAP.

The directive as stated points at **D**. Confirm the commitment before we start —
the first concrete move (§4.1, spine → `knowledge/canonical/`) is KEAP-side and
independently worth doing, so it can begin immediately once D is chosen.

## 7. Already settled
The `ent:` correction (reply §7) is already in `nos-cortex-lang.md` (§4 note + §12
item 1): `object_type_definitions` is a dead schema; P1 refuses `ent:` with a
constant `namespace_not_resolvable`; populating the registry is a P3 nOS-side prereq.
