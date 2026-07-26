# Cortex specs ledger — where each document lives and dies

Status: **P-4b Docs stage**, 2026-07-25. The cortex transplant left its paper
trail across two repos; this ledger says, per document, what is done, what is
superseded, what the organ carries, and what stays with the KEAP product. The
**KEAP repo is untouched** — the deletion pass there ("post-transplant
cleanup") happens only after C4 lands, and this ledger is its shopping list.

Statuses: `done` (landed, historical value only) · `superseded` (by what) ·
`live-here` (organ runtime doctrine — vendored under
`files/anatomy/cortex/docs/specs/`) · `live-keap` (product-side, stays) ·
`split` (parts move at a named stage).

## KEAP `docs/specs/`

| document | status | note | post-C4 cleanup |
| --- | --- | --- | --- |
| `onto1-composition-contract.md` | **live-here** (vendored) | the byte-identity contract both implementations must satisfy; the CI conformance gate's law | keep in BOTH repos while two onto1 implementations exist (design §7 Q4) |
| `cortex-full-scope-decision.md` | **live-here** (vendored) | the C1–C4 staging + the two corrections (no db_identity carry-over, no shared keap.db) | move wholly to nOS; KEAP copy becomes a pointer |
| `cortex-validate.md` | **live-here** (vendored) | the validate surface spec the daemon implements | move to nOS at C4 (KEAP loses the surface) |
| `cortex-cutover.md` | **live-keap** (added v1.29.0, NOT vendored) | the P-5 switch: `CORTEX_BACKEND_URL`, why it is a switch and not a failover, why the local modules survive one release, and `cortex.ontologyDrift` | delete with `server/cortex-*.ts` — it documents the KEAP half only, and once that half is gone the doc has no subject |
| `durability-and-integrity.md` | **live-here** (vendored) | ANN tuning measurements (float8/max_neighbors=20) + store integrity doctrine | split: ANN/organ half moves, KEAP data-dir half stays |
| `nos-cortex-lang-review-02.md` | **live-here** (vendored) | round-2 language review; P0 decisions baked into the port | archive after C4 (decisions are in code) |
| `recall-gate.md` | **live-here** (vendored 2026-07-25) | gate semantics v2; the gate + embedder colocate host-side (design §3) — C2 runtime, organ doctrine already | move at C2 |
| `ontology-anchoring.md` | **live-here** (vendored 2026-07-25) | domain packs + LLM context injector design — the organ's `/agent/v1/context` future | design work continues nOS-side |
| `nos-selfmodel-keap-contract.md` | **live-here** (vendored 2026-07-25) | the cross-repo self-model contract; the organ now RUNS the generator itself (C1-GAP-selfmodel.md) | keep in both until C4 (KEAP still ingests the fixture) |
| `nos-selfmodel-reply-01.md` | **done** | round-1 protocol agreement; content absorbed into the contract above | archive |
| `cortex-backend-boundary-reply.md` | **superseded** — §3's cortex-vs-product line was overturned by `cortex-full-scope-decision.md` ("The directive changes the answer") | measured ground truth in §1–2 remains a useful record | archive with a pointer to the scope decision |
| `handoff-nos-agent-2026-07-24.md` | **done** | v1.26.0 pin bump + the 07-22 wipe lesson; both acted on | archive |
| `conditional-relations.md` | **live-keap** | R4 roadmap over the typed-relations product pipeline (design, not built) | stays — follows the corpus (C2/C3) if ever built |
| `deploy-knowledge-mount-split.md` | **live-keap** | KEAP container mount doctrine ("all of knowledge/ or none") | stays — container deploy concern |
| `table-graph-metadata-spec.md` | **live-keap** | DataTables — the named exception that never moves | stays |
| `topic-mode-spec.md` | **live-keap** | explorer UI behaviour | stays |

## nOS `docs/plans/`

| document | status | note |
| --- | --- | --- |
| `nos-cortex-organ-design.md` | **live-here** | P-3 design; §2 table + §6 build sequence are what P-4/P-4b implement. Two of its intents (db_identity carry-over, shared keap.db) are OVERRIDDEN by the scope decision — the doc's §7 says so |
| `nos-cortex-organ-role.md` | **live-here** | this stage's plan + status |
| `nos-cortex-lang.md` | **live-here** | the language plan (P0/P-1/P-2 line); landed through KEAP v1.27.0, kept as design record |
| `nos-cortex-lang-wing-executor.md` | **split** | §8's network risk #6 dissolved by the organ placement (design §5); the executor half stays live for the Wing integration |
| `cortex-backend-boundary-decision.md` / `-rfc.md` | **superseded** | by `cortex-full-scope-decision.md`; kept as the decision trail |
| `cortex-specs-ledger.md` | **live-here** | this file |

## What the organ vendors (files/anatomy/cortex/docs/)

`C1-GAP-selfmodel.md` (locally authored) + the eight `specs/` above. Vendored
copies carry a provenance header (source repo @ tag); the KEAP originals stay
authoritative until the post-C4 cleanup executes the right-hand column.

**Audited 2026-07-26.** Three things this section claimed that the tree did not:

1. **Only 3 of 8 carried the header.** The five vendored with the P-4 code port
   (`cortex-full-scope-decision`, `cortex-validate`, `durability-and-integrity`,
   `nos-cortex-lang-review-02`, `onto1-composition-contract`) had none — the
   three vendored a day later in the Docs stage did. Stamped now, at v1.27.0,
   which is the tag the code port was cut from.
2. **One copy has already drifted**, and benignly, which is the useful part:
   `cortex-validate.md` cites `server/migrations.ts:60` while KEAP's cites `:83`,
   because v1.28.0's dead-schema comment shifted the line by 23. Both are
   correct *for their own tree*. That is the whole vendoring hazard in one
   diff — the copies are pinned to a snapshot, they will keep diverging, and
   **nothing gates it**. The organ's CI runs the organ's own fixtures and is
   structurally blind to divergence from the source. The only live detector is
   KEAP's `cortex.ontologyDrift` health field, and it watches the *ontology
   digest*, not the prose.
3. **`cortex-cutover.md` did not exist here.** Added above.

The header now says citations track the organ tree. That is a statement about
what these copies are *for* — reading the organ's code — not a licence to let
them rot. The post-C4 cleanup is what ends the duplication; until then, treat a
KEAP-side spec edit as owing a re-vendor.
