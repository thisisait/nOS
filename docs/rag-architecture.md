# RAG architecture

Authoritative design for nOS retrieval-augmented generation (RAG) — the
embeddings substrate that lets agents and operators ask "have we seen this
before?" and pull semantically-similar prior context out of past agent runs,
remediation history, and the service catalog.

> **Status: MVP — substrate LIVE, ingest pipeline DEFERRED (2026-06-14).** The
> vector DB (Qdrant), the host-side embeddings API (Bone), the read-only PHP
> client (Wing), and the consuming agent profile (librarian) are all shipped
> and contract-defined. What is NOT yet shipped is the **corpus-population
> pipeline** — the scheduled job that embeds agent outputs / system metadata /
> cybersec intel and upserts them into Qdrant. Until that lands, the store is
> empty and the librarian agent returns "awaiting corpus" rather than running
> RAG over zero points. This document is the MVP design plus the honest map of
> implemented-vs-deferred so a future operator or agent knows exactly where the
> seams are.

Related: `files/anatomy/plugins/qdrant-base/README.md` (the wiring half, with
the operator verification recipe), `apps/qdrant.yml` (the install half),
`files/anatomy/agents/librarian/{agent.yml,system.md,rubric.md}` (the consuming
agent contract), `docs/ait-runtime-architecture.md` (the AgentKit runtime that
hosts librarian), `docs/sso-and-attribution.md` (the agent matrix and runner
status).

## 1. Overview — RAG basics, nOS MVP scope

**RAG in one sentence:** instead of asking an LLM to answer from its frozen
training weights alone, you first **retrieve** the most relevant snippets from
your own corpus (by semantic similarity in a vector space), then **augment** the
prompt with those snippets, so the **generation** is grounded in your data.

The three moving parts:

1. **Embed** — turn text into a fixed-length vector that captures meaning, via an
   embedding model. Similar meaning → nearby vectors.
2. **Store + index** — keep those vectors (plus a small JSON payload of source
   metadata) in a vector database that does fast approximate k-nearest-neighbour
   (k-NN) search.
3. **Retrieve + generate** — embed the query, k-NN against the store, feed the
   top hits to the LLM as context.

**nOS MVP scope** is deliberately narrow and local-first:

- The corpus is **operator-owned platform telemetry**, not arbitrary documents:
  past agent run summaries, the Wing systems catalog, and cybersec intel
  (CVEs / advisories / remediation items). It is recall over *what the platform
  has already done*, not a general document search engine.
- Every byte stays on the host. No managed vector-DB SaaS, no external embedding
  API by default. The vector DB key never leaves the box (Bone owns it).
- The first and only first-class consumer is the **librarian** agent — a
  read-only "have we seen this before?" recall agent. It does not act; it
  produces an INPUT brief for an operator or for chaining to the remediator.

What the MVP is explicitly **not**: a chat-with-your-docs UI, a real-time index,
or a multi-tenant knowledge base. Those are out of scope for v0.7.

## 2. Corpus sources

Three first-class collections are reserved in the Qdrant plugin manifest. Each
is a separate Qdrant collection with its own dimension and its own producer:

| Collection | What it holds | Producer (intended) |
|---|---|---|
| `agent_outputs` | One point per agent run — embeddings of conductor / inspektor / remediator / gitleaks run summaries. | A8 conductor + each plugin's skill runner, on run completion. |
| `system_metadata` | Wing `/systems` rows mirrored as embeddings — semantic search over the service catalog ("find all systems running PHP 8.x in EU residency"). | A nightly Pulse job. |
| `cybersec_intel` | CVE descriptions, advisories, `remediation_items`, vendor patches — "find advisories like REM-002 across history". | Conductor + an ad-hoc ingest CLI. |

The canonical knowledge sources these collections derive from are the same ones
this repo treats as authoritative elsewhere: the `docs/` tree and `CLAUDE.md`
(operator runbook + doctrine), and the `events` / `agent_sessions` /
`remediation_items` rows in `wing.db` (the audit + framework history). RAG does
not introduce a new source of truth — it indexes the existing ones for fuzzy
recall.

These collections are **scaffolding only today**: the plugin manifest declares
the schema, but nothing PUTs the collections into Qdrant automatically yet, and
no producer writes points. See §6 (Limitations).

## 3. Architecture

The data path is a clean three-hop loop, with Bone as the single API surface so
the Qdrant key is never handed to an agent:

```
  ┌────────────┐   embed (Ollama)   ┌────────┐   POST /api/v1/embeddings/upsert  ┌────────┐
  │  corpus     │ ─────────────────▶ │ vector │ ─────────────────────────────────▶│ Bone   │
  │  source     │                    │ (768d) │                                   │ (host) │
  │ (events,    │                    └────────┘                                   └───┬────┘
  │  systems,   │                                                                     │ key
  │  CVEs)      │   ◀─── brief ──── librarian ◀── search results ◀── /search ─────────┤
  └────────────┘                       (agent)                                        ▼
                                                                                 ┌─────────┐
                                                                                 │ Qdrant  │
                                                                                 │ :6333   │
                                                                                 └─────────┘
```

**Daily Pulse jobs (the deferred ingest layer).** The corpus stays fresh via
scheduled host-side jobs run by the Pulse daemon (`files/anatomy/pulse/`):

- A nightly `system_metadata` sync — read Wing `/systems`, embed each row, upsert.
- A `cybersec_intel` refresh — embed new CVE / advisory / remediation rows.
- An `agent_outputs` hook — embed each agent run summary on `event_insert`
  (event-driven rather than nightly, so recall reflects the latest run).

These job definitions are the missing piece of the MVP (see §6); the plugin
manifest's `pulse_jobs:` block is forward-ready metadata for them.

**Embedding via Ollama.** Embeddings are produced locally by Ollama (the same
MLX-backed runtime that serves the agent models on Apple Silicon) using an
embedding model (e.g. a `nomic-embed-text`-class model). The producer calls
Ollama for the vector, then ships the **already-computed vector** to Bone.
Honest seam: **Bone does NOT embed.** `POST /api/v1/embeddings/upsert` accepts a
pre-computed `vector` per point; choosing the embedding model and computing the
vector is the producer's job. Keep the embedding model and its dimension
consistent across writes and queries to the same collection, or k-NN is garbage.

**Bone — the embeddings API (`files/anatomy/bone/`).** Bone owns the Qdrant API
key (passed via its launchd/systemd plist env `QDRANT_API_KEY`) and exposes
three JWT-scoped routes so the key never leaves the host:

- `GET  /api/v1/embeddings/health` (`nos:embeddings:read`) — Qdrant `/healthz`
  probe; agents use it as a precondition.
- `POST /api/v1/embeddings/upsert` (`nos:embeddings:write`) — upsert N points
  `{id, vector, payload}` into a collection.
- `POST /api/v1/embeddings/search` (`nos:embeddings:read`) — k-NN over a
  collection: `{collection, vector, limit, filter}`.

All three return **503** when `install_qdrant=false` (Qdrant URL empty). The Bone
client module is `files/anatomy/bone/clients/qdrant_client.py`.

**Qdrant — the vector store (`apps/qdrant.yml`).** Open-source, Rust-based,
Apache-2.0, Tier-2 app. Binds `127.0.0.1:6333` (HTTP) on the host; gRPC 6334
stays inside the apps Docker network. Storage persists in the `qdrant_storage`
volume. Telemetry is disabled. The web dashboard is Authentik forward-auth gated
to **admin tier only** (raw vector-DB management is power-user territory).

**Wing — the read-only consumer (`files/anatomy/wing/app/Model/QdrantClient.php`).**
A read-only PHP client (writes route through Bone for actor attribution). The
`/vector-search` route is reserved for the future cross-collection
similarity-search UI.

**librarian — the agent (`files/anatomy/agents/librarian/`).** The RAG consumer
in the AgentKit runtime: semantic search over `agent_outputs` /
`remediation_items` / GDPR rows, synthesised into a one-page recall brief. It is
strictly read-only, cites Qdrant point IDs + similarity scores, never fabricates
(if no point clears the threshold it says so), and never recommends fixes
(that's the remediator's job). The Authentik client `nos-librarian` is
pre-provisioned and reserved.

## 4. Operator workflow

**Enable the substrate** — set `install_qdrant: true` in `config.yml`, run the
playbook. See the qdrant-base README for the full first-blank checklist and the
known two-blank key-propagation gotcha (Bone reads `QDRANT_API_KEY` from env at
process start, so a second `ansible-playbook main.yml` run propagates the
freshly-generated key into Bone/Wing).

**Manually trigger the librarian** — the agent runs in the AgentKit runtime:

```bash
php files/anatomy/wing/bin/run-agent.php --agent=librarian --trigger=operator \
  --prompt="recall prior context for: <your query>"
```

Today, with an empty corpus, this returns a single
`[INFO] librarian: corpus empty — no recall available` and exits 0 — no event,
no fabricated brief. Once the ingest pipeline populates Qdrant, the same command
runs the RAG loop and emits a recall brief.

**View results** — the run is fully audited (`agent_sessions` row, OTel span,
token tally) and visible at:

- `/agents/librarian` — the agent detail page.
- `/agents/librarian/sessions/<uuid>` — the per-run deep dive (threads,
  iterations, Tempo trace deep-link).
- API: `GET /api/v1/agents/librarian/sessions` and
  `GET /api/v1/agent-sessions/<uuid>` (bearer auth).

Raw collection inspection (admin only) is the Qdrant dashboard at
`https://qdrant.apps.<tld>/dashboard`, gated behind Authentik.

## 5. GDPR compliance

Qdrant carries a complete Article 30 register row (`apps/qdrant.yml` `gdpr:`):

- **Legal basis: `legitimate_interests`.** Embeddings are derived from text the
  operator chose to process (audit logs, CVE descriptions, system facts);
  Qdrant does not collect data — it persists what Bone uploads.
- **Data subjects: operators** (plus automated agent systems). **No external
  processors; no transfers outside the EU** — the store is all-local.
- **Retention: 365 days.** This is the audit-trail + drift-baseline horizon.
  Indefinite retention (`-1`) is **rejected for derivative data** — re-embedding
  from the canonical sources is cheap, so there is no justification to keep
  vectors forever.

**Article 17 (erasure) — two enforced layers:**

1. **Prevention (Bone redaction).** `bone_redaction_required: true` in the
   plugin manifest is **enforced**, not just declared: Bone's
   `redaction.py::redact_payload` strips direct identifiers (operator email) from
   every upsert payload before it reaches Qdrant. Vectors are not reversible to
   source text, so the redacted payload is the only place a direct identifier
   could otherwise land. (The module fails open to identity only in a degraded
   env where it cannot be imported.)
2. **Erasure (delete-by-filter).** Qdrant is the one store with no other reach
   for the Art. 17 seam, so the Bone client exposes
   `delete_points(collection, *, ids=None, filter=None)` — delete by point-id
   list OR by a Qdrant payload filter (e.g. a `must` match on a subject). Today
   this is a **manual operator path**, not an automated DSAR hook — the operator
   (or a future erasure-map entry) invokes the delete explicitly. This is the
   honest current limitation: there is no per-point automatic erasure wired into
   the DSAR flow yet.

## 6. Limitations (MVP honesty)

- **No corpus yet — librarian is contract-only.** The three collections are
  declared but not auto-bootstrapped, and no producer writes points. The
  librarian runner detects `qdrant count > 0` as a precondition and emits
  "awaiting corpus" when zero. The ingest pipeline (the daily Pulse jobs + the
  `event_insert` embed hook) is the deferred piece — tracked in
  `docs/active-work.md` and `docs/sso-and-attribution.md` (agent matrix,
  `runner_status: deferred`, `deferred_reason: needs Qdrant corpus population
  pipeline`).
- **No real-time index.** Recall reflects the last ingest run (nightly for
  system/cybersec, event-driven for agent outputs) — not the live current state.
- **365-day retention ceiling.** Anything older than the retention horizon is
  out of recall by design (see §5).
- **No automatic per-point erasure in the DSAR flow.** Art. 17 erasure of
  individual points is a manual `delete_points` invocation today (§5).
- **Embedding-model consistency is the operator's responsibility.** Mixing
  embedding models or dimensions within one collection silently degrades recall;
  there is no runtime guard for it in the MVP.
- **Two-blank key propagation.** First `install_qdrant: true` blank leaves Bone
  with an empty key until a second run — see the qdrant-base README gotcha.
