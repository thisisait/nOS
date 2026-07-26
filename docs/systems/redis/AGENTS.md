# Redis — Agent Definition

## RedisSubstrate

**System:** Redis (`nos.infra.redis`, infra stack)
**Bind:** `127.0.0.1:6379` — loopback only, no domain, no SSO
**Role:** Passive in-memory cache / session store. Not directly agent-driven.

### Context

- Image `redis:8.6.3`; container `infra-redis-1`; reachable in-cluster as `redis:6379`.
- Password-gated by `requirepass` = `redis_password` = `{global_password_prefix}_pw_redis`.
- AOF persistence at host bind `{{ nos_data_root }}/platform/services/redis/data`; `maxmemory 256mb`, `allkeys-lru`.
- Gated by `redis_docker: true` (not `install_redis`). No HTTP API. No OIDC.

### Capabilities

- None invocable over an API. An agent interacts with Redis only indirectly — through a consuming service (Authentik, n8n) — or, for operator-supervised inspection, via `docker exec redis-cli`.

### Liveness

`docker exec infra-redis-1 redis-cli ping` → `PONG` (exit `0`).

### Skills Reference

See [SKILLS.md](SKILLS.md) — there is no external skill surface, and why.
