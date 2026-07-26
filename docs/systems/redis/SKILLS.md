# Redis — Skills

> **No external skill surface.** Redis is a headless in-memory cache, not an invocable HTTP service. There are deliberately no `**Trigger:**` skill nodes here.

## Why there are no skills

Redis exposes only the RESP wire protocol on `127.0.0.1:6379`, bound to loopback and password-gated. It has no REST/HTTP API, no dashboard, and no user-facing action an agent could invoke by calling an endpoint. It is a cache/session store — consuming services (Authentik server + worker, n8n) read and write keys over their own connections. Inventing "skills" here would fabricate endpoints that do not exist.

## Operator access (informational, not an agent skill)

Direct access is via the container shell, authenticating with `{global_password_prefix}_pw_redis`:

```bash
docker exec -it infra-redis-1 redis-cli -a <password>
```

## Liveness (informational)

The manifest health probe is an exec, not an API call:

```bash
docker exec infra-redis-1 redis-cli ping
```

A `PONG` reply (exit `0`) means the server is up.
