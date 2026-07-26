# ntfy

> Self-hosted pub/sub HTTP push-notifications server. Publish to a topic over
> plain HTTP; subscribe from phone, browser, or CLI. In nOS it is also an A9
> notification channel (`on_critical`/`on_high` route to `ntfy`).

## Quick Reference

| | |
|---|---|
| **URL** | `https://ntfy.<tenant_domain>` (default `https://ntfy.dev.local`; derived from `ntfy_domain`) |
| **Host port** | `2586` (loopback-bound → container port `80`; published on `0.0.0.0` only when `services_lan_access: true`) |
| **Stack** | `iiab` |
| **Node** | `nos.iiab.ntfy` |
| **Toggle** | `install_ntfy: true` (default `false`) |
| **Image** | `binwiederhier/ntfy:v2.26.3` (`ntfy_version`) |
| **Compose override** | `~/stacks/iiab/overrides/ntfy.yml` |
| **Data** | `{{ nos_data_root }}/platform/services/ntfy/data` (default `~/nos/platform/services/ntfy/data`) → mounted at `/var/cache/ntfy`, config at `/etc/ntfy/server.yml` |

## Authentication

- **Admin user:** none. ntfy provisions no admin account in nOS.
- **Access model:** `ntfy_auth_default_access: deny-all` — nothing is public.
  Access to the web UI / API is gated by **Authentik forward-auth** (Traefik
  middleware `authentik@file`); the Authentik session *is* the auth.
- **Signup / login:** `ntfy_enable_signup: false`, `ntfy_enable_login: true`.
- **SSO bucket:** `forward_auth` (Tier 3 = user). No native OIDC — ntfy has no
  OIDC client; Authentik gates access at the proxy layer only.
- **Bot token:** none provisioned by the playbook. ntfy supports `Authorization:
  Bearer tk_...` access tokens, but nOS does not create one — an external caller
  authenticates through the Authentik session. Internal callers on `iiab_net` /
  `shared_net` reach the container by name.

## API Access

- **Base URL:** `https://ntfy.<tenant_domain>` (public edge, forward-auth gated).
- ntfy has **no `/api/` prefix** — the topic name *is* the path: publish is
  `POST`/`PUT` to `/<topic>`, subscribe is `GET /<topic>/json`.
- **Auth:** Authentik forward-auth session (see above).

## Health Check

- **Endpoint:** `GET /v1/health` (container port 80).
- **Expected:** `200 OK` with `{"healthy":true}`.
- The compose healthcheck greps `"healthy":true` from `http://localhost:80/v1/health`.

## Dependencies

- Authentik (SSO forward-auth gate, optional — only when `install_authentik`).
- Traefik (edge proxy + `authentik@file` middleware).
- No database — ntfy keeps its own `cache.db` in the data directory.
