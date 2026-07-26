# Apache Superset

> Data visualization and BI. Dashboards, charts and SQL queries.

## Quick Reference

| | |
|---|---|
| **URL** | `https://superset.dev.local` |
| **Port** | `8089` |
| **Stack** | `data` |
| **Toggle** | `install_superset: true` |
| **Image** | `nos/superset:6.0.0-dev` — **built from source**, `files/superset/Dockerfile` on top of `apache/superset:6.0.0-dev` (`superset_version`) |
| **Compose** | `~/stacks/data/docker-compose.yml` |
| **Data** | **PostgreSQL** — database `superset`, user `superset` on the `postgresql` container. Dashboards, charts, datasets, users and saved queries all live there. |
| **Container mount** | `{{ superset_data_dir }}` = `{{ nos_data_root }}/platform/services/superset/data` → `/app/superset_home` (default `~/nos/platform/services/superset/data`) |
| **Config mount** | `~/stacks/data/overrides/superset_config.py` → `/app/pythonpath/superset_config.py` (read-only; config, not data) |
| **Cache / broker** | Redis (`redis:6379`) |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the bind mount
is overridden to `{{ external_storage_root }}/superset`
(`tasks/stacks/external-paths.yml`). Backing up Superset means backing up the Postgres
`superset` database; `/app/superset_home` holds only local cache / scratch.

> **The `-dev` tag is load-bearing.** `apache/superset:6.0.0` (non-dev) ships without any
> PostgreSQL Python driver and crash-loops with `ModuleNotFoundError: psycopg2`; the
> `-dev` variant bundles it. See `roles/pazny.superset/defaults/main.yml`.
>
> `state/manifest.yml` records `image: apache/superset` — that is the **base** image the
> local Dockerfile builds on, not the tag that runs.

## Authentication

- **Admin user:** `admin` (created by `superset fab create-admin` in
  `roles/pazny.superset/tasks/post.yml`; e-mail `superset_admin_email` =
  `admin@dev.local`)
- **Admin password:** `{global_password_prefix}_pw_superset`
- **SSO:** Authentik `native_oidc` (client `nos-superset`, slug `superset`, tier 2) —
  redirect URI `https://superset.dev.local/oauth-authorized/authentik`, wired through
  `OAUTH_PROVIDERS` in `superset_config.py`. Optional; gated on `install_authentik`.

## API Access

- **Base URL:** `https://superset.dev.local/api/v1/` (loopback: `http://127.0.0.1:8089/api/v1/`)
- **Auth method:** Bearer JWT from `POST /api/v1/security/login`
- **Bot account: none.** `roles/pazny.superset/tasks/post.yml` creates exactly one
  identity — the `admin` user above. There is no `openclaw-bot` and no
  `~/agents/tokens/` directory anywhere in this repo.
- **Credential location:** `~/.nos/secrets.yml` (prefix-derived), not a token file.

## Health Check

- **Endpoint:** `GET /health`
- **Expected:** `200 OK` with `"OK"`

## Dependencies

- PostgreSQL (metadata database — `superset` DB; this is where all Superset state lives)
- Redis (cache / celery broker — requires `redis_docker: true`, not `install_redis`)
- Authentik (native OIDC, optional)
