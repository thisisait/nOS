# Infisical

> Central secrets vault for infrastructure secrets — REST API + CLI. Infisical **CE**;
> several enterprise features (notably org-level OIDC SSO) are licence-locked, which
> shapes how nOS gates it. Runs in the `infra` stack; its authoritative state lives in
> PostgreSQL, not on disk.

## Quick Reference

| | |
|---|---|
| **URL** | `https://vault{host_alias_seg}.{tenant_domain}` (default `https://vault.dev.local`) |
| **Port** | `8075` (`infisical_port`; loopback publish `127.0.0.1:8075` → container `8080`) |
| **Stack** | `infra` |
| **Node id** | `nos.infra.infisical` |
| **Toggle** | `install_infisical: true` |
| **Image** | `infisical/infisical:v0.160.4` (`infisical_version`) |
| **Compose** | `~/stacks/infra/docker-compose.yml` (+ override `~/stacks/infra/overrides/infisical.yml`) |
| **Data** | `{{ nos_data_root }}/platform/services/infisical/data` → `/app/data` (default `~/nos/platform/services/infisical/data`) |
| **Authoritative state** | PostgreSQL database `infisical` (user `infisical`) on `postgresql:5432` + Redis. The bind mount is scratch/app state — **secrets live in the database**, wrapped by the KMS root key derived from `ENCRYPTION_KEY` |
| **Memory limit** | `1g` (`infisical_mem_limit` → `docker_mem_limit_standard`) |
| **Networks** | `infra_net` + the shared stacks network (`shared_net`) |

`infisical_version`, `infisical_domain` and `infisical_port` are pinned in
`default.config.yml` — that file **outranks** the role defaults. `infisical_data_dir`
is defined only in `default.config.yml`; an external-storage override relocates it to
`{{ external_storage_root }}/infisical` (`tasks/stacks/external-paths.yml`).

## Authentication

- **Admin user:** `infisical_admin_email` = `admin@{tenant_domain}` (`default.credentials.yml`).
  Bootstrapped on first seed by `roles/pazny.infisical/files/seed.py`, not "configured at first launch".
- **Admin password:** `infisical_admin_password` = `{global_password_prefix}_pw_infisical_admin`.
  (`{global_password_prefix}_pw_infisical_db` is the *database* password — a different secret.)
- **Organisation:** `infisical_org_name`, default `nOS`.
- **SSO bucket:** **`forward_auth`**, RBAC tier **1** — *not* native OIDC.
  Live-verified on v0.159.16 (2026-06-02): CE rejects org-OIDC with a plan restriction
  (`oidc_configs` = 0 rows, `/api/v1/sso/redirect/oidc` → 404), so the old `OIDC_*` env
  was inert and left this Tier-1 vault **ungated**. It is now gated at the edge by the
  Traefik `authentik@file` middleware (`traefik_auth_modes: infisical = proxy`,
  `files/anatomy/plugins/infisical-base/plugin.yml` `mode: forward_auth`).
  **Honest CE ceiling:** Authentik gates *access*, then Infisical still shows its own
  email + password form. Do not re-add `OIDC_*` env on CE.
  Break-glass when Authentik is down: `/login/admin`.
  > **Stale elsewhere — and it propagates.** The `infisical` row in `state/manifest.yml`
  > still carries `oidc: native`. The plugin manifest is the source of truth per
  > `roles/pazny.traefik/vars/main.yml`; the manifest field contradicts it and should
  > be corrected at the source. This is **not** a dead metadata field: the manifest
  > `oidc` value is read by `files/anatomy/scripts/keap_selfmodel_gen.py` (`render_service`,
  > which emits `- **SSO:** {sv['oidc']}`), so the cortex knowledge node for Infisical
  > currently asserts `SSO: native` while this page asserts `forward_auth`. Fixing the
  > manifest row is what closes the contradiction in the knowledge graph; editing only
  > this file cannot.

## API Access

- **Base URL:** `https://{infisical_domain}/api/` — note the API is **version-mixed**;
  there is no single `/api/v1/` surface.
- **Auth method:** Bearer JWT (`Authorization: Bearer <token>`).
- **Token:** `infisical_admin_token` — harvested from the seeder's bootstrap response
  and persisted to `~/.nos/secrets.yml` (re-rendered on every successful seed so the
  next run reuses the same identity). Empty string by default until the first seed.
  There is **no** `openclaw-bot` service token and **no** `~/agents/tokens/infisical.token`
  file — that pairing is a convention in `files/openclaw/AGENTS.md` that nothing provisions.
- **Endpoints actually exercised by the playbook** (`roles/pazny.infisical/files/seed.py`):
  `GET /api/v1/workspace` (list projects) · `POST /api/v2/workspace` (create project) ·
  `PATCH|POST /api/v3/secrets/raw/<key>` (upsert secret).
- Seeding runs on **every** playbook run (push-every-run policy): bootstrap fires once,
  then project-ensure + secret-upsert reconverge. Opt out with `infisical_seed_enabled: false`.

## Health Check

- **Endpoint:** `GET /api/status` → `200 OK` (manifest, the container healthcheck's
  `curl` and the role's readiness probe all use the same one).
- **KMS self-heal:** if readiness fails *and* the container logs show
  `Unsupported state or unable to authenticate data`, `post.yml` truncates the
  unrecoverable `kms_root_config` row, restarts the container and re-probes. Safe only
  pre-first-user — it is the wrapping key, and Infisical re-seeds it from the current
  `ENCRYPTION_KEY`.

## Dependencies

- PostgreSQL (secret store — required)
- Redis (cache — required)
- Authentik (edge forward-auth gate — optional but strongly recommended; without it a
  Tier-1 vault is exposed to anyone who can reach the route)
- Mailpit (SMTP relay, only when `install_mailpit` — optional)
