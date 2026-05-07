# redis-base

Wiring layer for the pazny.redis role. Headless in-memory cache + pubsub
substrate in the infra compose stack — backs Authentik (server + worker
session cache), n8n, and any other Redis-backed consumer. No app-level OIDC,
no Wing /hub card. Activates when `redis_docker: true` (nOS coexists a
Homebrew-native Redis with the Dockerized one; the flag picks which is the
live cross-stack path). Pinned to 7.4.6-alpine for CVE-2025-49844 (RediShell
RCE). Q3 batch.
