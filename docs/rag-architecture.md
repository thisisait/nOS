# RAG architecture

> **Status: Qdrant retired 2026-10-02.** The retrieval path is KEAP's own
> libSQL vector store. The earlier MVP design (Qdrant container, Bone
> `/api/v1/embeddings/*` proxy, Wing `QdrantClient`) shipped as a substrate and
> never gained a consumer: zero calls to the proxy, zero collections populated.
> It is gone from the repo; the history stays in `docs/devlog/` and `RELEASE.md`.

## What retrieves today

| Piece | Where | Notes |
|---|---|---|
| Vector store | KEAP (libSQL) — `docs/systems/keap/README.md` | 768-dim `nomic-embed-text`, rows beside the taxonomy they embed |
| Embedder | host Ollama, driven by the `keap-embed-sync` Pulse job (`files/anatomy/scripts/keap-embed-sync.py`) | runs host-side because the gated container cannot reach loopback Ollama |
| Query surface | KEAP `/agent/v1/embeddings` + `tools/keap-semantic-search.py`, the `keap-recall` skill, the `mcp-keap` AgentKit tool | read-only bearer for agents |
| Consumer | `files/anatomy/agents/librarian` (contract-only; runner still owed) | rubric §E names the KEAP corpus |

The GDPR posture of that store is KEAP's Article 30 row (`files/anatomy/plugins/keap-base/plugin.yml`
`gdpr:`); it is a derived corpus, re-embeddable from the canonical rows.

## What the retirement leaves behind on a live host

- The `qdrant` container drops out of `apps/overrides/auto.yml` on the next
  converge and `docker compose up --remove-orphans` removes it.
- Named volumes `apps_qdrant_storage` / `apps_qdrant_snapshots` are NOT removed
  by a converge; deleting them is the operator's call.
- The Authentik provider stays as a disabled tombstone in
  `state/tofu-authentik-services.yml` until OpenTofu has applied the destroy.
