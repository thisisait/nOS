# Cortex scope — what survived

> Vendored from thisisait/nos-keap @ v1.29.0 docs/specs/cortex-full-scope-decision.md — organ-side copy, vendored with the P-4 code port 2026-07-25. The KEAP original remains authoritative until the post-C4 docs cleanup; line-number citations here track the ORGAN tree, which is why they can differ from the original.

Status: **superseded on scope**, 2026-07-26, by nOS `docs/plans/cortex-self-core.md`.
Reduced from 117 lines to what is still true and still cited by code.

## What was overturned

The original drew the line at *what the code does* — cortex-vs-product, with
DataTables as a named exception — and staged the move as C1–C4. All of that is
dead. The boundary is now **publishability**: KEAP holds what can be published
(general taxonomy, ontology, trained weights); nOS holds the runtime and
everything private to the estate. DataTables moves, the UI moves with its source,
and KEAP ends as a data repository with no runnable server.

C1–C4 is replaced by S0–S6 in the plan above.

## What survives, and why it is still here

Three findings are still load-bearing and cited from live code in both repos
(`server/cortex-backend.ts` here; `cortex-store.ts`, `index.ts`,
`cortex-config.ts` in the organ).

### 1. C1's inputs are git-complete

Every DB read in `cortex-resolve.ts` / `cortex-validate.ts` /
`cortex-ontology-version.ts` is the FTS index over the tree, `relation_types`, or
the store's own identity. **Zero reads of `knowledge_objects`.**

That is why the organ needed no data migration to start. Confirmed by measurement
on 2026-07-26: its store holds 0 corpus rows.

### 2. Do not carry `db_identity` over at cutover

The field answers *"is this the same database?"* — it caught the 2026-07-22 wipe
and told the 07-24 `--remove=data` apart from a suspected converge bug. A cortex
store adopting KEAP's UUID makes that answer a lie on day one.

The counter-argument was false: bindings carry a TTL (default 900 s, clamped
[60, 3600]), so there is no population of long-lived pre-cutover ASTs to protect.
Worst case is one TTL of rejections, and a rejection *is* the mechanism working.
Drain by lowering `ttlSeconds` if even that is unwanted.

### 3. Do not share `keap.db`, not even read-only

Beyond the corruption risk: a reader cannot build its own tuned ANN index in a
file it does not own, so the organ would inherit the untuned 514 MB default and
lose the measured win entirely — and it defers the refactor with interest while
proving nothing about the end state.
