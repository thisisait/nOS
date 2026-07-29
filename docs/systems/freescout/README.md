# FreeScout

> Helpdesk system. Manages customer conversations and email.

## Quick Reference

| | |
|---|---|
| **URL** | `https://helpdesk{host_alias_seg}.{tenant_domain}` (default `https://helpdesk.dev.local`) |
| **Port** | `8090` (`freescout_port`; loopback publish `127.0.0.1:8090` → container `80`) |
| **Stack** | `b2b` |
| **Toggle** | `install_freescout: true` |
| **Compose** | `~/stacks/b2b/docker-compose.yml` (role fragment: `~/stacks/b2b/overrides/freescout.yml`) |
| **Image** | `nfrastack/freescout:2.1.5-php8.3` (`freescout_version`; bundles FreeScout 1.8.231) |
| **Data** | `{{ nos_data_root }}/platform/services/freescout/data` (default `~/nos/platform/services/freescout/data`) → `/data` |
| **Mem / CPU** | `freescout_mem_limit` (default `512m`) / `freescout_cpus` (default `0.5`) |

`nos_data_root` defaults to `~/nos` (`{{ HOME }}/nos`); `tasks/stacks/external-paths.yml`
relocates `freescout_data_dir` to `{{ external_storage_root }}/freescout/data` when
external storage is in play. Conversation content itself lives in **MariaDB** — `/data`
holds uploads, cache, and the generated app config.

**Image moved vendors:** `tiredofit/freescout` was EOL at 1.17.999 and bundled the
vulnerable FreeScout 1.8.219; the role now pulls `nfrastack/freescout` for the 2.x line
(bundles 1.8.226, above the CVE-2026-53595 CVSS-9.4 unauth-takeover fix at 1.8.224 —
REM-118). nfrastack 2.x renamed `SITE_URL` → `APP_URL`; the template sets both.

## Authentication

- **Admin user:** `{{ freescout_admin_email }}` — default `admin@{tenant_domain}`
  (`default_admin_email`). Auto-provisioned on first boot from the `ADMIN_EMAIL` /
  `ADMIN_PASS` env pair, not configured by hand.
- **Admin password:** `{global_password_prefix}_pw_freescout` (`freescout_admin_password`)
- **SSO:** `native_oidc` (Authentik OAuth2 client `nos-freescout`, slug `freescout`), RBAC tier **2**.
  - Redirect URI: `https://{freescout_domain}/oauth/callback`
  - Scopes: `openid`, `email`, `profile`
  - Env-driven via the `freescout-oauth` community module (`FREESCOUT_OIDC_*`), rendered
    by the plugin compose-extension.

## API Access

- **Base URL:** `https://helpdesk.dev.local/api/`
- **Auth method:** API key (`X-FreeScout-API-Key: <api-key>`)
- **Bot account:** none provisioned. No playbook task creates a FreeScout API key and
  nothing writes `~/agents/tokens/freescout.token` — generate one in Manage → API &
  Webhooks (the API module must be enabled) if an agent needs it.

## Health Check

- **Endpoint:** `GET /` — the container healthcheck curls `http://localhost:80/` and the
  plugin's `wait_health` probes `http://127.0.0.1:8090/`. Root `302`s to `/login`, which
  is `<400`, so `curl -f` passes. `start_period` is 120s: first boot runs composer plus
  the DB migrations.
- **Expected:** `2xx`/`3xx` (redirect to `/login`)

## Dependencies

- MariaDB (conversation + ticket store — required; DB `freescout`, user `freescout`)
- Authentik (native-OIDC SSO — optional)
- Mailpit (SMTP relay, only when `install_mailpit` — optional; otherwise the image's
  bundled postfix-relay default)
