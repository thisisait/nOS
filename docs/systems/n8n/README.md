# n8n

> Workflow automation — visual editor, 400+ integration nodes, webhooks. Filesystem-only
> state (no external DB): n8n's own SQLite `database.sqlite` lives in the mounted
> `/home/node/.n8n` alongside workflow definitions and encrypted credentials.

## Quick Reference

| | |
|---|---|
| **URL** | `https://n8n{host_alias_seg}.{tenant_domain}` (default `https://n8n.dev.local`) |
| **Port** | `5678` (`n8n_port`; loopback publish `127.0.0.1:5678` → container `5678`; LAN publish only when `services_lan_access: true`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.n8n` |
| **Toggle** | `install_n8n: true` |
| **Image** | `n8nio/n8n:2.28.1` (`n8n_version`; REM-109 pin — Jun-2026 advisory cluster, 4 HIGH) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/n8n.yml` (role) + `~/stacks/iiab/overrides/n8n-base.yml` (plugin extension) |
| **Container** | `iiab-n8n-1` |
| **Data** | `~/n8n` (`n8n_data_dir`) → `/home/node/.n8n`. Filesystem-only — `database.sqlite`, workflow definitions, encrypted credentials |
| **Memory limit** | `1g` (`docker_mem_limit_standard`) |
| **Networks** | `iiab_net` + `shared_net` (`stacks_shared_network`) |
| **Timezone** | `Europe/Prague` (`n8n_timezone` → `GENERIC_TIMEZONE` + `TZ`) |

`n8n_domain`, `n8n_port`, `n8n_version`, `n8n_data_dir` pin in `default.config.yml`; the
role defaults mirror them as fallbacks. The domain derives from `tenant_domain` +
`host_alias`, not a hardcoded `dev.local`.

> **The data path is OFF the `nos_data_root` doctrine — reported, not silently "fixed".**
> Every other Docker-service data dir derives from `{{ nos_data_root }}/...`
> (`docs/doctrine/filesystem.md`). `n8n_data_dir` is still the pre-doctrine
> `{{ ansible_facts['env']['HOME'] }}/n8n` in *both* `default.config.yml` and the role
> default, so `~/n8n` is the TRUE path today. It survives because the doctrine gate
> `tests/anatomy/test_fs_doctrine_paths.py` matches path vars with `^([a-z_]+)_data_dir:`
> — `[a-z_]+` cannot match the digit in `n8n`, so this var is invisible to the gate.
> Moving it is a migration (it relocates live SQLite), not a docs edit.

**External-storage override:** `tasks/stacks/external-paths.yml` re-points
`n8n_data_dir` to `{{ external_storage_root }}/n8n` when external storage is configured.

**Compose config lives under `~/stacks/`** and that is current and correct — only the
DATA row is governed by the `nos_data_root` scheme.

**Backup:** `backup_dirs_to_dump` tars `~/n8n` LIVE at 03:00 — no sqlite quiesce yet, so
a torn copy is possible; restic keeps 7 dailies. See `docs/backup-architecture.md`.

## Authentication

- **Owner (first) account:** created once by `roles/pazny.n8n/tasks/post.yml` via
  `POST /api/v1/owner/setup`.
  - user `{{ n8n_admin_email }}` — defaults to `default_admin_email`, i.e. `admin@{tenant_domain}`
  - password `{global_password_prefix}_pw_n8n` (`n8n_admin_password`)
  - The same post-task reconverges the password after a prefix change via
    `/rest/login` + `/rest/change-password`.
- **SSO:** `native_oidc` — Authentik OAuth2 client `nos-n8n`, RBAC tier 2. The env block
  is rendered by the `n8n-base` plugin compose-extension, not the role template:
  - `N8N_AUTH_OIDC_ENABLED`, `N8N_AUTH_OIDC_CLIENT_ID: nos-n8n`,
    `N8N_AUTH_OIDC_ISSUER: https://{authentik_domain}/application/o/n8n/`
  - Redirect URIs: `/rest/oauth2-credential/callback` and `/rest/oidc/callback`
  - Rendered only when `install_authentik` is true.
- **Autologin:** upstream CANNOT force-OIDC — `default.config.yml` records
  `sso_autologin_n8n` as unsupported. The local form stays.

## SSRF protection (REM-043)

`N8N_SSRF_PROTECTION_ENABLED: "true"` is default-ON here (default-OFF upstream). It
blocks the HTTP Request node and webhooks from reaching RFC-1918 + loopback — i.e. every
nOS peer on `shared_net` / `iiab_net` / `infra_net`. Re-open specific internal targets
with `n8n_ssrf_allowed_hostnames` / `n8n_ssrf_allowed_ip_ranges`; disable entirely with
`n8n_ssrf_protection: false`.

## Health Check

- **Endpoint:** `GET /healthz` → `200 OK`. The plugin `post_compose` health-wait polls
  `http://127.0.0.1:5678/healthz`; `roles/pazny.n8n/tasks/post.yml` waits on the same URL before the
  owner setup.
- **Container healthcheck:** `wget -qO- http://localhost:5678/healthz` (interval 30s,
  retries 3, start period 30s).

## Dependencies

- Authentik (native-OIDC SSO — optional; falls back to the local owner login)
- Mailpit (optional — when `install_mailpit` is on, n8n's SMTP relay points at
  `mailpit:1025`)
- No external database (filesystem-only `/home/node/.n8n`)
