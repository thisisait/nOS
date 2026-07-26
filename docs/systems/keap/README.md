# KEAP — Knowledge Explorer and Preserver

> The CORTEX of the nOS anatomy: the knowledge layer of the brain. A curated
> taxonomy, content links into the live content services, a capture/preservation
> review queue, and an agent-facing knowledge API (`/agent/v1`) consumed by the
> AgentKit runtime.

## Quick Reference

| | |
|---|---|
| **URL** | `https://keap{host_alias_seg}.{tenant_domain}` (default `https://keap.dev.local`) |
| **Agent surface** | `http://127.0.0.1:8091` (loopback publish, container binds `8080`) |
| **Port** | `8091` (`keap_port`; loopback publish + the AgentKit surface) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.keap` |
| **Toggle** | `install_keap: true` |
| **Image** | `nos/keap:{{ keap_version }}` (default tag `1.34.0`) — BUILT FROM SOURCE, cloned from `thisisait/nos-keap` at `keap_repo_ref` (`v1.34.0`) |
| **Data** | `{{ nos_data_root }}/platform/services/keap/data` → `/data` (default `~/nos/...`; external-storage override applies) |
| **Memory limit** | `512m` (`docker_mem_limit_light`) |
| **Network** | `gated_net` only (Traefik-only; SEC-02) |

Operator pins live in `default.config.yml` (`keap_domain`, `keap_port`, `keap_version`,
`keap_data_dir`, `keap_repo_ref`); role defaults are fallbacks. The domain derives from
`tenant_domain` + `host_alias`, NOT a hardcoded `dev.local`.

> **Never pin `v1.19.0` or `v1.20.0`** — both are real released tags that silently drop
> the self-model tree (see `roles/pazny.keap/defaults/main.yml` and
> `tests/anatomy/test_keap_pin_not_cancelled.py`). Self-model work needs `v1.21.0`+.

## Authentication

- **Human web access:** `header_oidc` (Authentik proxy outpost). Per-user rows are
  keyed by `X-Authentik-uid`; RBAC tier 3 (`nos-users`).
- **Header trust:** `KEAP_TRUSTED_PROXY=1` — header-less `/api` requests get `401`
  rather than falling back to a dev identity. Only Traefik's `authentik@file` on
  `gated_net` supplies legitimate headers.
- **Admin user:** none provisioned — admin capability is gated by Authentik group/tier,
  not a local account.
- **Agent access:** scope-split bearer tokens (see API below), NOT the human path.

## API Access

- **Base URL (agents):** `http://127.0.0.1:8091` — loopback only. Containers cannot
  reach a Docker-published loopback port, so only host-side AgentKit processes call it.
- **Auth header:** `Authorization: Bearer <token>`; optional `x-keap-agent: <agent-id>`.
- **Response envelope:** success payloads are wrapped `{"success": true, "data": {...}}`.
- **Scope-split tokens** (env, set by the playbook):
  - `KEAP_AGENT_TOKEN_RO` — read-only (`GET /agent/v1/...`).
  - `KEAP_AGENT_TOKEN_RW` — read + write (upserts, `lint/run`, `embeddings`).
  - `KEAP_AGENT_TOKEN_CAPTURE` — write-only device/intake (`POST /ingest/v1/capture`).
- **Public origin (browser/CSRF):** `KEAP_PUBLIC_URL = https://{keap_domain}`.

## Health Check

- **Endpoint:** `GET /api/health` — the image bakes a Docker `HEALTHCHECK` on it; the
  A19 health-wait polls `http://127.0.0.1:8091/api/health` (timeout 120s).
- **Agent-surface probes:** `GET /agent/v1/health`, `GET /ingest/v1/health`.

## Scheduled Jobs (host-side Pulse)

Four Pulse jobs (declared in `files/anatomy/plugins/keap-base/plugin.yml`) drive the
corpus nightly; each calls the loopback agent surface:

| Job | Schedule (UTC) | Endpoint(s) |
|-----|----------------|-------------|
| `keap-embed-sync` | `45 4 * * *` | `GET/POST /agent/v1/embeddings[/pending]` |
| `keap-features-sync` | `0 5 * * *` | `GET /agent/v1/features/vectors`, `POST /agent/v1/features` |
| `keap-consolidate` | `15 4 * * *` | `POST /ingest/v1/capture` |
| `keap-lint` | `15 5 * * *` | `POST /agent/v1/lint/run` |

## Dependencies

- Authentik (header-OIDC gate + identity headers)
- host Ollama (embeddings; the `gated_net` container cannot reach loopback Ollama, so
  `keap-embed-sync` runs host-side and posts vectors back — model `nomic-embed-text`, 768-dim)
- RO bind mounts: the git-cloned `knowledge/` SoT, the per-user files tree, and the
  generated self-model tree
- Optional: `pazny.cortex` organ (only when `keap_cortex_cutover: true` and image `v1.29.0`+)
