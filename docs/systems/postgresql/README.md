# PostgreSQL

> Shared OLTP relational datastore for the infra stack. Headless TCP substrate backing Authentik, Outline, HedgeDoc, Miniflux, BookStack and Wing/Bone telemetry.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.infra.postgresql` |
| **Bind** | `127.0.0.1:5432` (loopback only — no domain, no HTTP) |
| **Port** | `5432` (`postgresql_port`) |
| **Stack** | `infra` |
| **Toggle** | `install_postgresql: true` |
| **Image** | `postgres:16.14-alpine` (`postgresql_version`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` + `~/stacks/infra/overrides/postgresql.yml` |
| **Container** | `infra-postgresql-1` |
| **Data** | `{{ nos_data_root }}/platform/services/postgresql/data` → `/var/lib/postgresql/data` (host bind mount) |

## Authentication

- **Admin user:** `postgres` (`postgresql_root_user`)
- **Admin password:** `{global_password_prefix}_pw_postgresql` (var `postgresql_root_password`)
- **SSO:** None. PostgreSQL is a TCP service consumed over a DSN by other containers on `infra_net`; no OIDC client, no `authentik:` plugin block. Not exposed through Traefik.

## Access

- **No HTTP/REST API.** PostgreSQL speaks the libpq wire protocol on `127.0.0.1:5432`; not reachable off-host.
- **Consumers** connect over Docker DNS as `postgresql:5432` on `infra_net` / `shared_net`.
- **Operator CLI:** `docker exec -it infra-postgresql-1 psql -U postgres`.
- **In-transit TLS (macOS):** `postgresql_ssl_enabled` is `true` on Darwin — the role generates a self-signed server cert and runs `ssl=on`; libpq clients (`sslmode=prefer`) upgrade to TLS automatically. On Linux it defaults off (key-ownership constraint; see role defaults).
- **Tuning (`command:` block):** `max_connections=600`, `idle_session_timeout=300000` (5 min), `idle_in_transaction_session_timeout=60000` (1 min) — set to survive the Authentik 2025.x connection-pool leak.
- Service databases/users are declared centrally in `default.config.yml` / `default.credentials.yml`, not in the role.

## Health Check

- **Type:** exec (manifest `state/manifest.yml`)
- **Command:** `docker exec infra-postgresql-1 pg_isready -U postgres`
- **Expected:** exit code `0`
- **Compose-level probe:** `pg_isready -U postgres` (interval 10s, retries 10, start_period 15s)

## Upgrades

- **Recipe:** `upgrades/postgresql.yml`; breaking boundaries `15->16`, `16->17`.
- **Coexistence supported** (`coexistence_supported: true`) — major-version cutover uses the dual-track logical dump/restore path, not a raw data-dir clone.

## Dependencies

- None (headless substrate; auto-enabled by `main.yml` when a Postgres-backed consumer is toggled on).
- **Downstream consumers:** Authentik (identity tables + OAuth sessions), Outline, HedgeDoc, Miniflux, BookStack, Wing/Bone telemetry.
