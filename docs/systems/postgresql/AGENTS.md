# PostgreSQL — Agent Definition

## PostgreSQLSubstrate

**System:** PostgreSQL (`nos.infra.postgresql`, infra stack)
**Bind:** `127.0.0.1:5432` — loopback only, no domain, no SSO
**Role:** Passive OLTP datastore. Not directly agent-driven; consuming services own its rows.

### Context

- Image `postgres:16.14-alpine`; container `infra-postgresql-1`; reachable in-cluster as `postgresql:5432`.
- Superuser: `postgres` / `postgresql_root_password` = `{global_password_prefix}_pw_postgresql`.
- Data at host bind `{{ nos_data_root }}/platform/services/postgresql/data`.
- TLS on macOS (self-signed, `ssl=on`); tuned `max_connections=600` + idle-session reaping for the Authentik pool leak.
- No HTTP API. No OIDC. Auto-enabled when a Postgres-backed consumer is toggled on.

### Capabilities

- None invocable over an API. An agent interacts with PostgreSQL only indirectly — through the consuming service — or, for operator-supervised maintenance, via `docker exec` SQL, the `upgrades/postgresql.yml` recipe, and the coexistence dual-track for major-version cutovers.

### Liveness

`docker exec infra-postgresql-1 pg_isready -U postgres` → exit `0`.

### Skills Reference

See [SKILLS.md](SKILLS.md) — there is no external skill surface, and why.
