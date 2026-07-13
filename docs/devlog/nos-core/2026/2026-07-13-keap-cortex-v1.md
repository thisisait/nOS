---
id: 2026-07-13-keap-cortex-v1
title: "KEAP cortex reaches 1.0 — the knowledge organ ships GA"
date: 2026-07-13
namespace: nos-core
summary: "KEAP — the knowledge organ of the nOS anatomy — reaches its first GA (nos/keap:1.0.0), integrated Tier-1 and on by default. This arc lands the Track K knowledge-filling epic (778/778 load-bearing K1 descriptions plus node-article briefs for levels 0-2, agent-authored on cost-tiered models under one house style, embedded locally via Ollama), a MV3 browser capture extension with its own Authentik-free /ext/v1 edge route, per-tier data-table sharing with an opt-in fixture seed, and the backup/restore + agent wiring that make the cortex a durable, first-class service. Cut as an annotated v1.0.0 on the app release branch; nOS pinned and deployed (smoke 49/49); feat/keap-cortex fast-forwarded to dev."
tags: [keap, cortex, knowledge, release, rbac, extension, backup, taxonomy, ollama]
release: v0.8-beta

actors: [pazny, claude]
related: [RELEASE.md, docs/roadmap.md]
---
KEAP began as a seed: a 790-node taxonomy of human knowledge with almost no
text behind it. A node knew its name and its place in the tree, and little
else — 778 of the 790 carried no description at all, so the embedding for
"Kinematics" was built from the word "Kinematics" and a breadcrumb. A knowledge
organ that cannot describe what it knows cannot retrieve it. This tag is the
arc that filled the cortex, gave it a way to take in the world, taught it who
may see what, and made it survive a disk failure — and then stamped it 1.0.

## The filling — Track K

The descriptions are load-bearing by doctrine (DescGraph): the curated text
*is* the node's search and embedding surface, not decoration. So the first job
was to write all 778 of them, and the second was to write the articles that
hang beneath them — several explanatory paragraphs per node with mandatory
`[[node-id]]` cross-links and durable external references. Both were authored
by the `librarian` agent, not by hand.

Two structural decisions made that affordable and coherent. First, **model
tiers**: the runner honours a per-ceremony `NOS_AGENT_MODEL`, so the bulk
description sweep runs on haiku and the article + judgment ceremonies on
sonnet — a bulk job never silently inherits the operator's flagship default.
The symptom that forced it was a $4-a-batch describe run; the fix took it to
cents. Second, a shared **house style** contract in the agent prompt and the
skill docs: one encyclopedic voice, one fixed term per concept reused across
nodes, Czech mirroring English 1:1 — so the corpus reads as a single reference
work rather than 790 essays. Embeddings are generated locally through Ollama
(`nomic-embed-text`), so filling the whole corpus cost nothing at the API.

One bug surfaced mid-sweep and is worth remembering: the promotion dup-guards
read open proposals through a default `LIMIT 200`, so past 200 pending
proposals they went blind and re-served nodes that were already queued,
minting duplicates. The fix was an uncapped `openPromotions()` feeding all six
guard sites plus an init-time dedupe — a reminder that a silent cap in a
read path is a correctness bug, not a performance knob.

## The intake — a browser that captures

A cortex needs a mouth. The MV3 companion extension pairs to a KEAP instance
and pushes pages and selections into the moderated review queue. The
load-bearing lesson was at the edge, not in the code: an extension is a
**cross-origin, cookieless caller**, so the browser never attaches the
Authentik session cookie to its fetches. Routed through the normal
SSO-gated vhost, the pairing request came back as the *login page* — an
HTML 200 the extension reported as "non-JSON response". The fix mirrors the
device-ingest route: `/ext/v1` gets its own Traefik router with **no Authentik
middleware**, because the server already runs that surface before the identity
layer and enforces its own pairing-bootstrap-plus-Bearer auth. A pre-release
security review (two adversarial agents) then closed a RustFS row-id
path-traversal, a `javascript:`-URL XSS in the article renderer, and a
fail-closed CSRF guard on pairing approval.

## The tiers — who may see what

The R2′ TableStore let anyone read a table if it was "shared" — a single
tenant-wide flag, blind to the four nOS access tiers. This arc threads the
Authentik groups through as a tier rank and widens the visibility scope to
`private | tier-managers | tier-users | tier-guests | shared` (reusing the
existing column, no migration): a scope grants read to its tier and every tier
above it, guests are read-only, and a new `PATCH` route lets an owner re-scope
a table after creation. To make the feature legible on a fresh install — and
to double as a live RBAC demo — an opt-in **fixture seed** offers three
illustrative, OLAP-shaped demo tables, one per scope, once, behind a marker.

## The survival — backup that keeps the vectors

KEAP's entire dataset lives in one libSQL file: the taxonomy, the curated
descriptions and briefs, the data-table registry and rows, and the vector
corpus. It was **entirely uncovered by the nightly backup**. The subtlety is
the vector index — it uses `libsql_vector_idx()`, a function host `sqlite3`
does not have, so the usual `.dump`/replay path cannot reconstruct it. The
answer is the online `.backup` API: a page-level copy that is WAL-consistent
and carries the vector pages intact, restored as a file move into a stopped
container rather than a SQL replay. And the Admin › Taxonomy tab, which had
been rendering a sparse metadata overlay (roots showing as "unnamed"), was
rebuilt on the real 790-node tree with the K1 descriptions, depth-indented.

## GA

Cut as an annotated `v1.0.0` on the app repo's release branch; nOS pinned
`keap_repo_ref: v1.0.0`; deployed live with `nos/keap:1.0.0` healthy,
`failed=0`, smoke `49/49`, and the tier matrix, fixture seed, and `/ext/v1`
JSON all confirmed against the live edge. `feat/keap-cortex` fast-forwarded to
`dev`. The `dev → master` PR cuts the nOS tag as its own ceremony.
