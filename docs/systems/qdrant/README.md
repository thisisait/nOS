# Qdrant

> Vector database for the agentic platform: embeddings + payload, searched by similarity. Tier-2 manifest app (`apps/qdrant.yml`) — deployed by apps_runner, not by an Ansible role.

## Quick Reference

| | |
|---|---|
| **Host port** | `127.0.0.1:6333` (HTTP API, `qdrant_port`); gRPC `6334` stays inside `apps_net` |
| **Stack** | `apps` |
| **Toggle** | `install_qdrant: false` (default.config.yml:1767) |
| **Image** | `docker.io/qdrant/qdrant:v1.13.4` |
| **Container** | `qdrant` (pinned `container_name:`, not the `<stack>-<svc>-1` pattern) |
| **Compose** | `~/stacks/apps/overrides/auto.yml` — the MERGED Tier-2 file; Qdrant owns no fragment of its own, which is why its manifest row carries `fragment: null` |
| **Manifest node** | `nos.apps.qdrant` |

## Authentication

- **API key:** `QDRANT__SERVICE__API_KEY` (read-write) and `QDRANT__SERVICE__READ_ONLY_API_KEY`, both resolved from magic tokens by apps_runner.
- **SSO bucket:** `forward_auth` — the Traefik router carries `authentik@file`. There is no per-user identity inside Qdrant.
- `/healthz` and `/metrics` answer without the key (Prometheus scrape path).
- Telemetry is off (`QDRANT__TELEMETRY_DISABLED=true`); Qdrant phones home by default.

## What lives in it

Derived data only — embeddings of agent outputs, Wing systems rows and cybersec advisories. Every point is re-embeddable from the canonical rows elsewhere, which is why the GDPR retention horizon is 365 days rather than forever.

## Dependencies

- apps_runner (renders the merged compose file), Traefik (edge + forward-auth), Bone (the only sanctioned ingestion path, and therefore the redaction point).
