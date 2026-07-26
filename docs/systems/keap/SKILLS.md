# KEAP — Skills

> Callable actions for the KEAP cortex. All are API-first against the loopback agent
> surface `http://127.0.0.1:8091`, authenticated with scope-split bearer tokens.

## Authentication

- **Method:** Bearer token (scope-split)
- **Base URL:** `http://127.0.0.1:8091`
- **Header:** `Authorization: Bearer <token>` (plus optional `x-keap-agent: <agent-id>`)
- **Tokens:** `KEAP_AGENT_TOKEN_RO` (read), `KEAP_AGENT_TOKEN_RW` (write),
  `KEAP_AGENT_TOKEN_CAPTURE` (intake only)
- **Envelope:** responses are wrapped `{"success": true, "data": ...}` — unwrap `data`

---

## get-feature-vectors

**Trigger:** "read taxonomy embeddings", "get node feature vectors", "what vectors does the cortex hold"
**Method:** API
**Endpoint:** `GET /agent/v1/features/vectors`
**Token:** RO
**Output:** the container's taxonomy embeddings for downstream feature computation

---

## upsert-features

**Trigger:** "write node features", "update GraphCanvas features", "push computed features to the cortex"
**Method:** API
**Endpoint:** `POST /agent/v1/features`
**Token:** RW
**Input:** `{ "model": "<embed-model>", "features": [ ... ] }`
**Output:** upserted `node_features` (read by the GraphCanvas)

---

## fetch-embedding-pending

**Trigger:** "what needs embedding", "list pending embeddings", "which corpus items are stale"
**Method:** API
**Endpoint:** `GET /agent/v1/embeddings/pending?limit=<n>`
**Token:** RW
**Output:** `{ "items": [...], "model": "<name>", "dim": <int>, "total": <int>, "pruned": <int> }`
(server caps `limit` at 500; empty `items` means the corpus is current)

---

## upsert-embeddings

**Trigger:** "store embeddings", "post vectors back to the cortex", "save computed embeddings"
**Method:** API
**Endpoint:** `POST /agent/v1/embeddings`
**Token:** RW
**Input:** the vectors computed for the pending items (dim must match the `pending` response)
**Note:** the host-side `keap-embed-sync` Pulse job is the reference caller — it embeds
via host Ollama (`nomic-embed-text`, 768-dim) because the `gated_net` container cannot
reach loopback Ollama.

---

## run-lint

**Trigger:** "lint the knowledge base", "reconcile cortex drift", "run the corpus lint"
**Method:** API
**Endpoint:** `POST /agent/v1/lint/run`
**Token:** RW (it is a write — it reconciles state)
**Output:** lint outcome; the `keap-lint` Pulse job fans failures into the A9 notification path

---

## read-lint

**Trigger:** "show lint findings", "any knowledge-base issues", "read the last lint result"
**Method:** API
**Endpoint:** `GET /agent/v1/lint`
**Token:** RO
**Output:** the current lint findings (read-only view of the last reconcile)

---

## submit-capture

**Trigger:** "capture this page", "add to the preservation queue", "ingest a datapoint", "save for review"
**Method:** API
**Endpoint:** `POST /ingest/v1/capture`
**Token:** CAPTURE
**Input:** a capture envelope (text/metadata/geo, media-by-reference). The capture id is a
sha1 of the source key, so re-captures UPDATE the same review-queue row rather than duplicate.
**Output:** the queued capture (lands in the human review queue like every other capture)

---

## read-config-tables

**Trigger:** "read KEAP config tables", "get the shell DataTables", "fetch face layout config"
**Method:** API
**Endpoint:** `GET /agent/v1/tables`
**Token:** RO (RW for the write path)
**Output:** the config DataTables — the source of truth the nOS face shell reads for its layout
**Note:** the list-all form can `401` on some builds; the shell fetches per-table.

---

## validate-cortex-source

**Trigger:** "typecheck cortex-lang", "validate a pipeline source", "resolve tax/rel opcodes"
**Method:** API
**Endpoint:** `POST /agent/v1/validate` (and `GET /agent/v1/validate/opcodes`)
**Token:** RO
**Input:** `{ "source": "<nos-cortex-lang>", "ttlSeconds": <int> }`
**Output:** an AST or a typed error — tokenize → typecheck against the live ontology, zero side effects
**Note:** with `keap_cortex_cutover: true` (image `v1.29.0`+) this proxies to the `pazny.cortex` organ.
