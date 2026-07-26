# Cortex → nOS self-core, and bring-your-own-data

Status: **plan, not started.** Written 2026-07-26. Supersedes the C2–C4 staging in
KEAP `docs/specs/cortex-full-scope-decision.md`, which drew its boundary in the
wrong place (see §3).

**Read §1 and §2 before acting on anything below.** This plan will be executed by
agents who have not seen the systems it describes, possibly weeks after it was
written. §2 is what makes it safe to trust — or to stop.

---

## 1. Orientation — what these systems are

**nOS** is an Ansible-managed personal/company estate: ~74 roles, mostly Docker
services behind Traefik, plus four *host organs* that run as native daemons
(launchd on macOS, systemd --user on Linux):

| organ | job |
| --- | --- |
| **Bone** | signals and credentials |
| **Wing** | executes and observes; owns the operator console UI and the job registry |
| **Pulse** | keeps time; fires scheduled jobs and reports every run to Wing |
| **Cortex** | remembers and reasons — the newest, and the subject of this plan |

**KEAP** (Knowledge Explorer And Preserver) is a separate repo: a React/three.js
explorer over a taxonomy of ~1 800 concept nodes, with an Express/TypeScript
backend on libSQL (SQLite + a DiskANN vector index). It has been the system that
holds knowledge.

**What already happened.** The cortex organ (`roles/pazny.cortex`,
`files/anatomy/cortex/`) exists and works. It is a verbatim port of KEAP's
reasoning modules, running as a loopback daemon on `127.0.0.1:8098`, serving
`POST /agent/v1/validate` — a typechecker for `nos-cortex-lang`, a small
pipeline language an LLM emits and Wing dispatches. It materialises its own store
from git plus a generator that describes the estate. KEAP v1.29.0 can proxy its
validate calls to it (`CORTEX_BACKEND_URL`).

**What did not happen.** The organ holds **zero embeddings, zero corpus rows**.
It can typecheck a program; it cannot answer a question. That is tracked as
`docs/hidden_fees/10-cortex-organ-cannot-recall.md` and it is what this plan
closes.

### The point of the whole thing

Cortex is meant to become **the nOS self-core plus a bring-your-own-data
runtime**: a system that knows what the estate is, ingests an organisation's own
material, and lets business logic be described against it — connected upward to
formal sciences and to the legislation the organisation must follow.

KEAP's taxonomy is **reference and test data**, not the product. The product is
the runtime.

---

## 2. The measured present

Every number below was measured on 2026-07-26 against the live estate.
**Re-measure before acting.** If a number has moved by more than the tolerance,
stop and report rather than adapting silently — the plan's decisions were made on
these values.

| fact | value | tolerance | how to re-measure |
| --- | --- | --- | --- |
| KEAP corpus, durable payload | **~11.5 MB** | ±50 % | sum of `knowledge_objects` + `api_taxonomy_metadata` + `taxonomy_metadata` + `embeddings.vector` lengths |
| corpus rows with **no source outside the container** | **0** | must stay 0 | every `knowledge_objects.id` is `fs:*` or a converge-seeded table row; all 128 captures are `source=app`, `origin=filesystem` |
| KEAP `keap.db` file | 565 MB | — | `docker exec iiab-keap-1 ls -la /data/keap.db` |
| …of which vector index | **513.8 MB** | — | `sum(length(data))` on `embeddings_vec_idx_shadow` |
| embeddings | 3 355 · 9.8 MB of vectors | — | `count(*)`, `sum(length(vector))` on `embeddings` |
| full embed pass | 17.7 s | — | Pulse log, `keap-embed-sync` |
| KEAP agent API surface | 49 endpoints, ~40 corpus-facing | — | grep `app.(get\|post)` in `server/agent.ts` |
| KEAP UI API surface | 54 routes, ~33 corpus-facing | — | grep `'/api/` in `server/*routes*.ts` |
| `server/db.ts` | 2 966 lines — the single data chokepoint | — | `wc -l` |
| KEAP repo | 3.46 MiB packed, no LFS | — | `git count-objects -vH` |
| fs-sync source | `{{ nos_data_root }}/tenants/<slug>/users`, bind-mounted RO | — | `compose.yml.j2` |
| …and `nos_data_root` resolves to | **`/Volumes/SSD1TB/nOS/data`** — an **external, removable volume** | — | `config.yml:201` |
| fs-sync id derivation | `fs:<uid>:<sha1(relPath)[:16]>`, uid = top-level directory NAME | must stay deterministic | `server/fs-sync.ts` |
| fs-sync visibility | from the config `SHARED_UIDS` set, **not** filesystem permissions | — | `server/fs-sync.ts:479` |

**The finding that shaped this plan:** the corpus is 11.5 MB and *nothing in it
lacks an external source*. The earlier framing — "C2 moves a store with no git
source" — was false. This is not a data migration. It is a migration of
**ownership**, and the data can be rebuilt rather than copied.

---

## 3. The boundary rule

Two earlier attempts drew this line by asking *what does the code do* (cortex vs
product; then everything-except-UI). Both needed exceptions almost immediately.

**The rule is publishability:**

> **KEAP holds what can be published. nOS holds the runtime and everything
> private to the estate.**

| | goes to | because |
| --- | --- | --- |
| general taxonomy, ontology, formal sciences, legislation | **KEAP** | publishable reference data |
| trained model weights + their vocabulary | **KEAP** | publishable artefact; the community is expected to extend it |
| the estate self-model | **nOS** | private |
| corpus, embeddings, fs-sync, captures, curator, lint, topics | **nOS** | private, and it is the runtime |
| **DataTables** | **nOS** | estate state, not reference data. This reverses the "named exception" in the superseded scope decision |
| KEAP explorer UI | **nOS**, as a native host service | the source moves too — vendoring it would be a third drifting copy (`hidden_fees/11`) |

After the move **KEAP is a data repository only** — no server, no UI, no release
train for code. It becomes a HuggingFace-shaped artefact: versioned data plus
versioned weights, synced into nOS at converge.

### The doctrine line this generated

> If the API is the only observable path, an in-process shortcut is an
> unobservable call — and it is forbidden, however trivial.

Now in `docs/doctrine/observability.md`. It binds the UI, Pulse and Wing to
`/agent/v1` even once they are colocated with the store.

---

## 4. Versioning the weights

Weights are not data and must not be versioned like data. A weights artefact is
only meaningful together with **the vocabulary it was trained on** and **the code
that turns text into vectors**. We already have the mechanism: `onto1:<hash>`
stamps the ontology, and a validated AST carries it so a consumer can tell when
the language moved. Weights get a sibling — `emb1:<hash>` — and an embedding is
valid only while **both** hold. The binding triple becomes a quartet.

**Storage: git-LFS for published weights, rustfs (S3) for training checkpoints.**

The deciding argument is the stated goal — *"vypustí se na firemní server a začne
fungovat"*. A manifest-plus-S3 scheme (cheaper, and the estate already runs
rustfs with backups) produces an artefact that a third party cannot resolve.
Published weights must be **self-contained**, which is what LFS buys and what
HuggingFace itself does. Checkpoints are ours and never leave, so they take the
cheap path.

Cost to accept, explicitly: the KEAP repo stops being 3.5 MB, and every converge
that syncs weights pulls binaries. Mitigation is a manifest gate — a weights
entry whose blob is unresolvable must fail **loudly**, never silently degrade to
"no weights". *Absence is not emptiness* is already doctrine here.

---

## 5. Scale — what "millions of nodes" actually costs

libSQL's DiskANN stores, at each graph node, copies of its neighbours' vectors so
traversal needs no random reads. That is the whole 153 KB/vector. The arithmetic
matches the measurements exactly:

| configuration | per vector | at 1M nodes |
| --- | --- | --- |
| default (~50 neighbours × 768 dims × 4 B) | 153 KB | ~153 GB |
| `compress_neighbors=float8` | 66.9 KB | ~67 GB |
| `max_neighbors=20` | 62.5 KB | ~62 GB |
| both | **19.5 KB** | ~20 GB |
| both, at **128 dims** | **~4.6 KB** | **~4.6 GB** |

**The two knobs do not cost the same.**

- `float8` quantizes only the neighbour copies used for *routing*; the final
  distance is computed from the stored full-precision vector. The error changes
  which candidates get visited, not how they rank. It degrades gracefully and is
  close to free.
- `max_neighbors` lowers graph connectivity, and greedy search can then settle in
  a local minimum. **This risk grows with corpus size.** At 3 355 vectors a
  degree-20 graph is still richly connected — which is why the harness measured
  100 % recall@10 — and that measurement does not transfer to 10⁶. DiskANN
  practice for large corpora is R=64–128.

**Therefore:** `float8` is a decision. `max_neighbors` is a **scale-dependent
parameter that must be re-measured at every order of magnitude**, not a constant.

**And therefore the last row matters most.** 768 dimensions is a property of
`nomic-embed-text`, not a law. A custom embedding space over the compression
language — the long-term ML goal — at 128 dimensions turns ~20 GB into ~4.6 GB.
The trained model is not only about meaning; **it is the principal lever on index
size**, and that is a reason to build it, not a side effect.

Out of scope here and owed its own research: at 10⁶ nodes the single libSQL file,
FTS5, and the explorer's force simulation all need their own answer.

---

## 6. Roadmap

Stages are sequential. Each has an **exit criterion that is measurable** — not
"done" but "X is true". Each begins by re-verifying the §2 facts it depends on.

S0–S3 have workflow definitions in `tools/workflows/`. **S4–S6 deliberately do
not** — their shape depends on what S0 answers and what S2 finds, and a workflow
written now would be a guess wearing the costume of a plan. Write each one when
its predecessor's report exists.

### S0 — Verify (blocking)

`tools/workflows/cortex-s0-verify.js`

Re-measure §2. Confirm zero corpus rows lack an external source. Confirm the
organ still reports `onto1:5d9bef3706a3c8ac`, or explain the delta.

**Exit:** every §2 number reproduced or its change explained in writing.

### S1 — Docs become knowledge

`tools/workflows/cortex-s1-docs-as-knowledge.js`

Replicate repo documentation into cortex as typed nodes — `hint`, `note`,
`skill`, `snippet`. This is first because it is the **primary corpus**: cortex is
a self-core, so the estate's own documentation is the product, not a fixture.

It also pays `hidden_fees/04` rather than triggering it: today `docs/systems/`
covers 22 of ~60 systems and points at paths that predate `nos_data_root`. Once
these are embedded, a router answers confidently for a third of the estate — and
silence is indistinguishable from "no such capability".

And it is the worked example. How we document our own systems is what we are
telling future users and their LLMs to copy.

**Exit:** every installed service has at least one typed node; the recall gate
runs against the estate's own docs with a stated denominator; no card cites a
path that does not exist.

### S2 — Corpus in parallel, not migrated

`tools/workflows/cortex-s2-corpus-parallel.js`

The organ builds its corpus from the **same host sources** KEAP uses — fs-sync
reads `{{ nos_data_root }}/tenants/<slug>/users` directly (the bind mount
disappears rather than being re-plumbed), the consolidator and embed-sync get a
second target. Both corpora run side by side and are **diffed**.

No copy, no cutover moment, reversible at every point. It is affordable only
because of §2's finding.

**Exit:** organ and KEAP corpora agree on row counts and ids within a stated
tolerance, for three consecutive nights.

### S3 — Index, decided on the gate

`tools/workflows/cortex-s3-index.js`

The parallel period is the measurement `hidden_fees/09` always needed and could
never get: **one corpus, two indexes, one recall gate**. Establish the baseline
against KEAP's untuned index, measure the organ's tuned one, accept only a
variant that holds.

**Exit:** recall gate shows no regression against baseline; index size recorded
per vector; `max_neighbors` documented as scale-dependent with the value used and
the corpus size it was measured at.

### S4 — Readers and writers move

Pulse jobs, Wing AgentKit and the curator/librarian agents repoint at the organ.
Then the KEAP UI's ~33 corpus routes. Per §3's doctrine line, everything goes over
`/agent/v1` — no in-process shortcut even once colocated.

**Exit:** no consumer reaches KEAP's corpus; every corpus read and write appears
in Wing's audit lineage.

### S5 — KEAP becomes data-only

UI source moves into nOS as a native host service. KEAP's server and UI code are
deleted; `server/cortex-*.ts` goes with them (`hidden_fees/11` closes). KEAP's
release train becomes dataset versioning.

**Exit:** KEAP repo contains no runnable server; nOS serves the explorer natively;
one implementation of onto1 remains.

### S6 — Weights

The `emb1:` stamp, the LFS layout, the manifest gate, and the training pipeline
over the compression language. Deliberately last: it needs a corpus that exists
and a vocabulary that has stopped moving.

**Corpus skew is a precondition, not a detail.** Measured 2026-07-26: KEAP's
taxonomy puts **67 % of its 1 750 nodes in 2 of 12 domains** (natural sciences
811, formal sciences 354; the other ten have zero curated extensions), and **58 %
of L1 branches have no children**. An embedding space fitted to that as it stands
learns the shape of physics and mathematics and treats the rest as sparse noise —
including Law, which is a childless stub and which the stated use case
(*business logic connected to the legislation a company must follow*) depends on.

Rebalancing, reweighting or growing the corpus is therefore S6 work that starts
before any training does. `knowledge/DATASET.md` carries the per-domain table.

**Exit:** a weights artefact resolvable by a third party from a clone alone, and
a written statement of what the corpus it was fitted to over- and
under-represents.

---

## 6b. The store and identity model

Decided 2026-07-26, after §8.1 found the identity claim aspirational. This
replaces "one store, one API, identity solves visibility".

### Per-user stores, two tiers

Each user's material lives in **their own libSQL file inside their own tree** —
the same doctrine class 3 that fs-sync already follows: the filesystem is the
boundary, not a `visibility` column. **Bone already does this**
(`files/anatomy/bone/userstate.py`: `_db_path(uid)` →
`{data_root}/tenants/<slug>/users/<uid>/.face/state.db`, `chmod 0700`, WAL), so
the pattern is estate precedent rather than invention.

It buys four things: the enumeration oracle for private data closes
*structurally* rather than by filter; GDPR erasure becomes deleting a file; the
vector index shards, which is a real answer to §5's size problem; and backup
becomes per-user.

**But it is never one store.** Measured today: 166 of 170 objects are `shared`,
3 are `tier-users`, **1** is `private`; 3 057 of 3 355 embeddings are the shared
tree. The ratio inverts once company data arrives, but the shape does not — every
useful question needs the shared vocabulary *plus* the asker's own material. So
the model is **shared reference store (read-only, opened by all) + personal store
(read-write, opened by one)**, always joined. Design it; do not discover it in S2.

### Two identities, and only one needs a token

| identity | for | mechanism |
| --- | --- | --- |
| **cortex-as-itself** | estate-wide work: self-model, nightly consolidation, serving shared reference data | Authentik OAuth2 `client_credentials` — Bone's `auth.py` already implements the verification, and the librarian/curator agents are the precedent |
| **cortex-for-user-X** | reading and writing X's own store | **the OS.** The process runs as the Unix user; the kernel decides. No token is involved in reading one's own data |

That second row is the important one: it removes the JWKS graft from the common
path entirely. A bearer is then needed only to talk to other services and to
prove **on whose behalf** cortex acts.

**And that is the gap with no existing answer.** "I am cortex acting for akadmin"
is on-behalf-of / token exchange, which `client_credentials` cannot express.
Nothing in the estate or in Authentik's current configuration does this today. It
is the one piece of the identity design that must be researched rather than
assembled.

Cost of the spawn model: one Node runtime per active user (~50–80 MB), and
lifecycle differs by platform — launchd user agents need the user logged in;
`systemd --user` needs lingering (`roles/pazny.linux.systemd_user` exists).
Mitigation is spawn-on-demand with an idle timeout.

**Blast radius warning, and it is not hypothetical.** Bone's per-user DB is
selected by a uid **parameter** behind a static shared bearer
(`require_face_token`); `_validate_uid` checks path traversal, not authorization.
So any holder of that token can name any uid. Per-user stores move the oracle
from a `WHERE` clause into a **file path**, where getting it wrong leaks a whole
store rather than a row. Copy Bone's layout; do not copy its enforcement. Tracked
as `hidden_fees/13`.

### `ent:` resolves against DataTables

`ent:` was blocked on `object_type_definitions` — created by migration 001,
touched by zero lines of code, never a row. The registry it needed already exists
under a different name:

```
data_tables: id, user_id, title, description, schema_json, driver, visibility
table_rows:  table_id, row_id, data
table_row_history
```

User-defined schema, per-user ownership, visibility, a storage-driver
abstraction, and history. That is the shape `ent:` needs, with live rows and a
live consumer. **`ent:` resolves against DataTables; `object_type_definitions`
gets dropped.**

This also settles what DataTables *is*. It was defended as a product exception,
then reclassified as estate state; both were wrong. It is **the entity registry —
the missing half of the language**, and that is why it belongs beside the
reasoning it serves.

Two sources feed it, split by the same boundary rule as everything else:

- **Estate entities** — services, jobs, runs, events, findings. These live in
  Wing's database and Nette's `Explorer` is the ORM. Reflecting them yields
  `ent:service`, `ent:job`, `ent:run` **immediately, with real rows**, before any
  company data exists. That is a far cheaper route to a working `ent:` than
  waiting for BYOD.
- **Company entities** — declared or inferred from imported material.

`ent:` resolution and AgentKit's tools (`McpKeapTool`, `McpWingTool`,
`McpBoneTool`) **must share one registry**. Two disagreeing views of what exists
is worse than no `ent:` at all.

---

## 7. Ingestion beyond the estate

The bring-your-own-data path, recorded so the design does not get fitted to the
estate alone:

- **Filesystem consent at converge.** A default list of candidate paths in config
  (home, media, mounted disks) and a `y/n` per path at the start of the run.
  Consent is per-path, asked, and recorded — never inferred from a mount being
  present.
- **First real import target: Google Drive / Docs / Photos / Calendar.** Note the
  ownership: **that is nOS core's job**, not cortex's. Core lands each kind of
  data into the right system; cortex consolidates overnight. Cortex does not grow
  a connector per SaaS.
- **Later: SharePoint import, or simply a mounted disk.**

The design constraint that follows: cortex's ingest surface takes *material and
provenance*, and knows nothing about where it came from.

---

## 8. Open questions

| # | question | blocks | owner |
| --- | --- | --- | --- |
| 1 | p95 latency of the ~33 UI routes once they cross the API — does the explorer need a named cache in front? | S4 | measure in S2 |
| 2 | ~~Does a caller identity unlock `kg:`/`ent:`?~~ **ANSWERED 2026-07-26, and the answer is no — not yet.** See §8.1 | S4 | now owed work, not a question |
| 3 | ~~fs-sync visibility and tenant scoping outside the container~~ **ANSWERED — de-risked.** See §8.2 | S2 | closed |
| 4 | **NEW:** the user tree is on a removable volume and only Docker has a mount preflight. See §8.3 | S2 | design in S2 |

### 8.1 The identity claim is aspirational

KEAP's `cortex-full-scope-decision.md` makes caller identity **the** argument for
the whole transplant: KEAP's agent surface cannot have one where it lives, but a
host organ behind Bone's loopback token + Authentik JWKS would — and that is the
precondition for `kg:`/`ent:` to ever resolve.

Measured: the organ contains **zero references** to Bone, JWKS or Authentik. Its
`agentAuth` was lifted verbatim from KEAP — one scope bit from a process-wide
secret, `x-keap-agent` self-asserted and believed by nothing. **Today the organ's
identity model is exactly as poor as KEAP's.**

The capability does exist, but in the wrong language: `files/anatomy/bone/auth.py`
has real JWKS caching, Authentik OAuth2 `client_credentials`, and scope checking.
Grafting it means either a **new TypeScript dependency** (organ deps today are
`express`, `libsql`, `zod` — no JWT library, and KEAP has none either) or a
cross-language hop the organ design explicitly rejected ("without Python Bone
proxying the TypeScript core").

**Nothing in this plan schedules it.** It is not a blocker for S1–S3, which need
no caller identity. It IS a blocker for the promise, and the honest position is:
`kg:`/`ent:` stay refused until this is built, and the transplant's headline
benefit is owed rather than delivered.

### 8.2 fs-sync is safer to move than assumed

The plan called this "the likeliest source of hidden coupling". It is not.
Doctrine class 3 makes the filesystem the boundary: the uid is the **top-level
directory name**, the object id is `fs:<uid>:<sha1(relPath)[:16]>`, and visibility
comes from a config `SHARED_UIDS` set. None of it reads uid ownership or
permissions, so a host daemon reading the same path derives the **same ids and the
same visibility** as the container does.

Two consequences: the container-vs-host permission worry was unfounded, and S2's
diff harness gets much sharper — the two id sets should match **exactly**, not
within a tolerance.

The prune guards are also already correct and only need porting: zero files found
while mirrors exist refuses the prune, an unreadable subtree truncates the walk
and forbids pruning against it, and `pruneRefused` is surfaced as data so a
refusal is observable rather than looking like "nothing to remove".

### 8.3 The removable volume has no host-side guard

`nos_data_root` is `/Volumes/SSD1TB/nOS/data` — the user tree lives on an
**external volume**. The estate knows this: `tasks/stacks/docker-external-mount-preflight.yml`
guards it. But that preflight protects **containers**, and a host daemon reading
the path directly goes nowhere near it.

So the guard that exists today does not cover the consumer S2 creates. fs-sync's
own refuse-to-prune logic (§8.2) is the second line and would hold, but relying on
it means the organ's correctness depends on a guard reacting to an unmounted disk
rather than on never walking one. **S2 must add a host-side mount assertion**, and
the workflow's `user-data` lens should hunt specifically for this.
| 4 | Single libSQL file, FTS5 and force-sim at 10⁶ nodes | after S3 | own research |
| 5 | What ends KEAP's code release train — a final tag, or a repo split? | S5 | decide in S4 |
