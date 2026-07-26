# MariaDB

> Shared MySQL-family relational datastore for the infra stack. Headless TCP substrate backing WordPress, Nextcloud, FreeScout, BookStack and any other MariaDB-backed consumer.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.infra.mariadb` |
| **Bind** | `127.0.0.1:3306` (loopback only — no domain, no HTTP) |
| **Port** | `3306` (`mariadb_port`) |
| **Stack** | `infra` |
| **Toggle** | `install_mariadb: true` |
| **Image** | `mariadb:11.8.8` (`mariadb_version`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` + `~/stacks/infra/overrides/mariadb.yml` |
| **Container** | `infra-mariadb-1` |
| **Data** | Docker **named volume** `mariadb_data` → `/var/lib/mysql` (NOT a host bind mount) |

## Authentication

- **Admin user:** `root` (`MARIADB_ROOT_HOST: "%"`)
- **Admin password:** `{global_password_prefix}_pw_mariadb` (var `mariadb_root_password`)
- **SSO:** None. MariaDB is a TCP service consumed over a DSN by other containers on `infra_net`; it has no OIDC client and no `authentik:` plugin block. Not exposed through Traefik.

## Access

- **No HTTP/REST API.** MariaDB speaks the MySQL wire protocol on `127.0.0.1:3306`; it is not reachable from outside the host.
- **Consumers** connect over Docker DNS as `mariadb:3306` on `infra_net` / `shared_net` / `gated_b2b_net`.
- **Operator CLI:** `docker exec -it infra-mariadb-1 mariadb -uroot -p<password>`.
- **Character set:** server default `utf8mb4` / `utf8mb4_unicode_ci`.
- Seed databases and users are declared centrally in `default.config.yml` (`mariadb_databases`, `mariadb_users`), not in the role.

## Health Check

- **Type:** exec (manifest `state/manifest.yml`)
- **Command:** `docker exec infra-mariadb-1 healthcheck.sh --connect`
- **Expected:** exit code `0`
- **Compose-level probe:** `healthcheck.sh --connect --innodb_initialized` (interval 10s, retries 10, start_period 30s)

## Storage note

Data lives in a Docker **named volume** (`mariadb_data`), not at a host path. On Apple Silicon Docker Desktop, backing `/var/lib/mysql` with a VirtIOFS bind mount crashes the InnoDB engine mid-FK-ALTER (OS error 71 / EPROTO). The var `mariadb_data_dir` (`{{ nos_data_root }}/platform/services/mariadb/data`) is defined but is **not** the storage location. Consequence: data is not host-browsable; back up with `mariadb-dump` (see `upgrades/mariadb.yml`). `docker compose down --volumes` (blank reset) wipes the named volume.

## Dependencies

- None (headless substrate; auto-enabled by `main.yml` when a MariaDB-backed consumer is toggled on).
- **Downstream consumers:** WordPress, Nextcloud, FreeScout, BookStack.
