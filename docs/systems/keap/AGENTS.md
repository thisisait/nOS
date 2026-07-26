# KEAP — Agent Definition

## CortexAgent

**System:** KEAP (iiab stack) — the nOS cortex / knowledge layer.
**Agent surface:** `http://127.0.0.1:8091/agent/v1` and `/ingest/v1` (loopback only).
**Role:** Reads and maintains the estate's knowledge corpus — taxonomy, node
features, embeddings, and the capture review queue — on behalf of AgentKit.

### Context

- Loopback agent surface, reachable only from host-side processes (containers cannot
  reach a Docker-published loopback port).
- Auth is scope-split bearer tokens: RO (read), RW (write), CAPTURE (intake only).
  Header `Authorization: Bearer <token>`; identify yourself with `x-keap-agent: <id>`.
- Responses are wrapped `{success, data}` — unwrap `data`.
- Human identity is `header_oidc`; the agent path is separate and never inherits it.

### Capabilities

- Read the taxonomy feature vectors (`GET /agent/v1/features/vectors`, RO).
- Upsert node features (`POST /agent/v1/features`, RW).
- Drive the embedding pipeline (`GET /agent/v1/embeddings/pending`,
  `POST /agent/v1/embeddings`, RW).
- Run and read the knowledge lint (`POST /agent/v1/lint/run` RW, `GET /agent/v1/lint` RO).
- Submit captures to the review queue (`POST /ingest/v1/capture`, CAPTURE token).
- Read config DataTables (`GET /agent/v1/tables`, RO/RW) — the shell layout SoT.
- Typecheck `nos-cortex-lang` (`POST /agent/v1/validate`, `GET /agent/v1/validate/opcodes`, RO).

### Skills Reference

See [SKILLS.md](SKILLS.md) for the callable actions with endpoints and tokens.
