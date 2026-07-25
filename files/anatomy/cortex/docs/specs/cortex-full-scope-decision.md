# How much of KEAP becomes the cortex organ

Status: **decision**, taken 2026-07-25 under an operator directive to consider
moving all of KEAP except the SoT data and the UI into nOS as the core cortex.
Supersedes the scope half of `cortex-backend-boundary-reply.md` §3, which drew
the line at cortex-vs-product without weighing the organ integrations.

## The directive changes the answer, and here is why

My earlier position was that the honest line is **cortex-vs-product**, not
backend-vs-UI: KEAP legitimately keeps a backend for its own product surfaces
(fs-sync, DataTables, captures, curator, lint), because those are not reasoning.

That reasoning was sound about *what the code does* and incomplete about *what
the placement buys*. Weighing the organ integrations — observability, backups,
RBAC, identity — moves the line, for one reason that dominates the rest:

> **KEAP's agent surface has no caller identity, and cannot get one where it
> lives.** `agentAuth` yields a single scope bit from a process-wide secret, and
> `req.agentName` comes from a self-asserted `X-Keap-Agent` header. That is why
> `validate` must declare `scope.authorizes: false` and refuse `kg:`/`ent:`
> outright rather than resolve them.

As a host organ behind Bone's loopback token + Authentik JWKS, with a Bone audit
event per call, a caller identity **exists**. That is not a security nicety — it
is the precondition for `kg:` and `ent:` to ever resolve, i.e. for the cortex to
answer questions about *objects* and not only about the taxonomy. Everything
that serves agents inherits that upgrade by moving. Nothing inherits it by
staying.

The other three integrations reinforce it and none contradict it: restic already
covers host paths (the container volume needed a bespoke pre-wipe snapshot to get
the same guarantee), Pulse already runs `keap-embed-sync`, and Wing's `events`
lineage is where audit belongs.

**So: yes to the move, with one named exception and a staged sequence.**

## What moves, what stays

| component | verdict | why |
| --- | --- | --- |
| `validate` / `resolve` / `context` / opcode registry | **moves** | the reasoning surface; and its inputs are already git-complete (below) |
| taxonomy tree, `relations`, `relation_types`, `onto1` | **moves** | the vocabulary the reasoning is typed against |
| embeddings, ANN index, hybrid search, `/graph` | **moves** | recall is remembering; the embedder is already host-side |
| **fs-sync** | **moves** | memory ingestion. As a host organ it watches host paths *directly* — the `/user-files` bind-mount disappears rather than being re-plumbed |
| **captures / intake** | **moves** | memory ingestion, and the layer that just needed a bespoke backup because it lived in a container volume |
| **curator / lint / promotions / topics** | **moves** | knowledge quality and clustering; all read the corpus and the embeddings |
| **DataTables** (`data_tables`, `table_rows`, `table_row_history`, `/agent/v1/tables`) | **STAYS** | the named exception — see below |
| explorer, admin, panels, the whole `src/` UI | **stays** | this is the point |
| `knowledge/` (spine, canonical, ontology) | **stays in git**, read by both | it is a repo, not a runtime |

### Why DataTables is the exception

It is a product feature with its own store and its own consumer (the nOS face
reads it through `/agent/v1/tables`). It does no reasoning: no embeddings, no
resolution, no vocabulary. Moving it would mean the organ whose definition is
*"remembers and reasons"* also owns a spreadsheet backend, and the next
ambiguous feature would have no line to be judged against.

It is the one place where "everything except the UI" costs more in clarity than
it buys in tidiness. If it later wants to leave KEAP, it should become its own
thing, not a lodger in the cortex.

## The sequence, and why C1 is genuinely first

The staging is not caution — it follows from a measured property of the code.

**C1 — `validate` (this is P-4, already designed).** Its inputs are
**git-complete**: every DB read in `cortex-resolve.ts` / `cortex-validate.ts` /
`cortex-ontology-version.ts` is the FTS index over the tree, `relation_types`, or
the store's own identity. **Zero reads of `knowledge_objects`.** The tree comes
from `knowledge/spine` + `knowledge/canonical` (P-1), the verbs from
`knowledge/ontology` — so the organ materialises everything it needs from git and
touches KEAP's store not at all. That is why C1 needs no data migration, no
shared file, and no two-writer decision: those questions belong to C2.

**C2 — the corpus and its ingestion.** `knowledge_objects`, fs-sync, captures,
embeddings, the ANN index, hybrid search, `/graph`. This is the real migration:
it moves a store with no git source (cards come from the filesystem, captures
from devices). It is where the two-writer question actually lives, and the answer
there is the one already written into the P-3 plan: KEAP reads through the API,
never a second writer on one libsql file.

**C3 — the quality pipelines.** curator, lint, promotions, topics. They follow
the corpus; moving them before C2 would strand them from their inputs.

**C4 — KEAP becomes the UI it is named for.** Delete `server/cortex-*.ts`, point
the client at the organ, keep DataTables and the product surfaces.

## Two corrections that must survive into P-4

Both are written as intent in the current P-3 plan and both are wrong:

1. **Do not carry `db_identity` over at cutover.** The field exists to answer
   "is this the same database?" — it is what caught the 2026-07-22 wipe and what
   distinguished the 07-24 `--remove=data` from a suspected converge bug. A cortex
   store that adopts KEAP's UUID makes that answer a lie on day one. The premise
   is also false: bindings carry a TTL (default 900 s, clamped [60, 3600]), so
   there is no population of long-lived pre-cutover ASTs to protect — worst case
   is one TTL of rejections, and a rejection *is* the mechanism working. If even
   that is unwanted, drain by lowering `ttlSeconds` before the switch.
2. **Do not share `keap.db`, not even read-only, not even transitionally.** Two
   reasons beyond the corruption risk: a reader cannot build its own tuned ANN
   index in a file it does not own, so the organ would inherit the 514 MB default
   and lose P-3's measured win entirely; and it defers the C4 refactor with
   interest while proving nothing about the end state. C1 makes the question moot.

## What this does not decide

- **When.** C2 moves a store with no git source and deserves its own design pass.
- **Whether `kg:`/`ent:` open up once identity exists.** It becomes *possible*;
  whether the enumeration-oracle exposure is acceptable per-identity is a separate
  call, and `object_type_definitions` still needs a writer before `ent:` means
  anything.
- **The KEAP repo's fate.** It keeps the UI, DataTables, `knowledge/` and its
  release train. It does not become a thin client this quarter.
