# Redis

> Shared in-memory cache + pubsub substrate for the infra stack. Headless TCP service backing Authentik (server + worker session cache), n8n, and any other Redis-backed consumer.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.infra.redis` |
| **Bind** | `127.0.0.1:6379` (loopback only — no domain, no HTTP) |
| **Port** | `6379` (`redis_port`) |
| **Stack** | `infra` |
| **Toggle** | `redis_docker: true` (NOT `install_redis` — see note) |
| **Image** | `redis:8.6.3` (`redis_version`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` + `~/stacks/infra/overrides/redis.yml` |
| **Container** | `infra-redis-1` |
| **Data** | `{{ nos_data_root }}/platform/services/redis/data` → `/data` (host bind mount, AOF) |

> **Toggle note.** The Dockerized Redis is gated by `redis_docker` (default `false`), not `install_redis`. nOS coexists a Homebrew-native Redis with a containerized one; `redis_docker: true` lights up this role and its `redis-base` plugin for cross-stack Docker consumers. The manifest carries `install_flag: install_redis`, but the role default and the plugin `feature_flag` are both `redis_docker` — that is the real switch.

## Authentication

- **User:** none (Redis has no user model on this version's config path).
- **Password:** `requirepass` = `{global_password_prefix}_pw_redis` (var `redis_password`) — mandatory since CVE-2025-49844.
- **SSO:** None. Redis is a TCP service consumed by other containers on `infra_net`; no OIDC client, no `authentik:` plugin block. Not exposed through Traefik.

## Access

- **No HTTP/REST API.** Redis speaks the RESP wire protocol on `127.0.0.1:6379`; not reachable off-host.
- **Consumers** connect over Docker DNS as `redis:6379`, authenticating with `requirepass`.
- **Operator CLI:** `docker exec -it infra-redis-1 redis-cli -a <password>`.
- **Runtime config (`command:`):** `--appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru --requirepass <redis_password>`.

## Health Check

- **Type:** exec (manifest `state/manifest.yml`)
- **Command:** `docker exec infra-redis-1 redis-cli ping`
- **Expected:** exit code `0` (replies `PONG`)
- **Compose-level probe:** `redis-cli -a <password> ping` (interval 10s, retries 5)

## Dependencies

- None (headless substrate; requires `redis_docker: true`).
- **Downstream consumers:** Authentik (server + worker session cache), n8n.
