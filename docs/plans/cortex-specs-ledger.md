# Cortex docs — the map

Rewritten 2026-07-26 for the publishability boundary
(`cortex-self-core.md` §3). The previous version mapped a cortex-vs-product
split that no longer exists.

**One rule.** A document lives where its **subject** lives. KEAP holds what can
be published; nOS holds the runtime. Specs about the runtime therefore end up in
nOS — but they move **with their code**, at the stage that moves it, not before.
Moving paperwork ahead of its subject leaves a repo whose code has no spec.

## In force

### nOS `docs/plans/`

| document | what it governs |
| --- | --- |
| **`cortex-self-core.md`** | **the plan.** Boundary rule, measured present, S0–S6 roadmap, weights versioning, scale. Start here |
| `nos-cortex-organ-design.md` | the organ's build record. Three open questions now resolved in place; §6 step 13's delete-and-flip is superseded by the KEAP cutover |
| `nos-cortex-lang.md` | the language design record. Landed through KEAP v1.27.0; `cortex-validate.md` is the normative spec |
| `nos-cortex-lang-wing-executor.md` | Wing's dispatch half — **forward design, not built** |
| `cortex-specs-ledger.md` | this file |

### KEAP `docs/specs/` — runtime specs, awaiting their code

These describe the runtime, so by the boundary rule they belong in nOS. They move
at the stage named in the last column. Eight are **vendored** into
`files/anatomy/cortex/docs/specs/` today; that duplication is
`hidden_fees/11` and ends when the original is deleted rather than copied.

| document | vendored | moves at |
| --- | --- | --- |
| `cortex-validate.md` | ✓ | S5 — the language spec follows the validator |
| `recall-gate.md` | ✓ | S3 — the gate is what decides the index |
| `durability-and-integrity.md` | ✓ | S3 — its §4 is the index decision |
| `onto1-composition-contract.md` | ✓ | S5 — needed in **both** while two implementations exist |
| `nos-selfmodel-keap-contract.md` | ✓ | S1 — the organ already runs the generator itself |
| `ontology-anchoring.md` | ✓ | S1 — the context injector is docs-as-knowledge's sibling |
| `cortex-full-scope-decision.md` | ✓ | S5 — reduced 2026-07-26 to the three findings code still cites |
| `nos-cortex-lang-review-02.md` | ✓ (organ only) | already only here — KEAP's original was deleted |
| `table-graph-metadata-spec.md` | — | S5 — DataTables moves, and it is the `ent:` registry |
| `topic-mode-spec.md` | — | S5 — with the explorer UI |
| `conditional-relations.md` | — | S5 — R4 design, follows the relations it extends |
| `deploy-knowledge-mount-split.md` | — | **dies at S5** — it is about a container that stops existing. Its open items are `hidden_fees/12` |
| `cortex-cutover.md` | — | **dies at S5** — documents the KEAP half of a switch that is deleted with it |

### KEAP keeps, permanently

Nothing in `docs/specs/` today. After S5 the repo is data and weights, and its
documentation is about **the dataset**: what the taxonomy covers, how the
ontology is structured, how weights are versioned and what they were trained on.
None of that is written yet — it is S6's deliverable.

## Vendoring rules

1. **Edit the original, then re-vendor.** Never edit a copy — the change is
   invisible to the repo that owns the subject and dies at the next re-vendor.
2. **Every vendored file carries a provenance header** naming the source repo and
   tag. Gated by `tests/anatomy/test_cortex_vendored_docs.py`.
3. **A KEAP-side spec edit owes a re-vendor.** Nothing enforces this across
   repos; the only live detector is `cortex.ontologyDrift` on KEAP's health, and
   it watches the ontology digest, not prose.

## Deleted 2026-07-26

Kept in git history; deleted because a superseded document costs every reader the
time to work out that it does not apply.

| document | why |
| --- | --- |
| `cortex-backend-boundary-rfc.md` + `-decision.md` | the boundary they decided was overturned twice since |
| `nos-cortex-organ-role.md` + `tools/workflows/nos-cortex-organ-role.js` | P-4b stage plan and its workflow; the work landed |
| KEAP `cortex-backend-boundary-reply.md`, `handoff-nos-agent-2026-07-24.md`, `nos-selfmodel-reply-01.md`, `nos-cortex-lang-review-02.md` | replies, handoffs and round-1 protocol; absorbed or acted on |
