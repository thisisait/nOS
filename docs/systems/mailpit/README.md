# Mailpit

> SMTP capture-all sink with a modern web UI and REST API. Default-on dev mail
> relay: every nOS service that sends mail (Authentik, Infisical, n8n, Outline,
> ERPNext, FreeScout, BookStack, HedgeDoc, Firefly, Miniflux, Watchtower) relays
> into `mailpit:1025` and the captured messages appear at `mail.<tld>`.

## Quick Reference

| | |
|---|---|
| **URL** | `https://mail.<tenant_domain>` (default `https://mail.dev.local`; derived from `mailpit_domain`) |
| **Web UI / REST port** | `8025` (host loopback → container `8025`) |
| **SMTP relay port** | `1025` (host loopback → container `1025`; apps relay here, **not** fronted by Traefik) |
| **Stack** | `iiab` |
| **Node** | `nos.iiab.mailpit` |
| **Toggle** | `install_mailpit: true` (default **on**) |
| **Image** | `axllent/mailpit:v1.30.5` (`mailpit_version`) |
| **Compose override** | `~/stacks/iiab/overrides/mailpit.yml` |
| **Data** | `{{ nos_data_root }}/platform/services/mailpit/data` (default `~/nos/platform/services/mailpit/data`) → `MP_DATABASE=/data/mailpit.db` (SQLite) |
| **Retention** | `mailpit_max_messages: 5000` (older messages auto-pruned) |

## Authentication

- **App-layer auth:** optional HTTP basic auth on the UI via
  `mailpit_ui_user` / `mailpit_ui_password` — **both empty by default, so basic
  auth is disabled**. When empty, `MP_UI_AUTH` is not set.
- **SSO bucket:** `forward_auth` (Tier 1 = admin). No native OIDC — Mailpit only
  supports HTTP basic auth on the UI; Authentik gates the UI at the Traefik layer.
- **SMTP auth:** `MP_SMTP_AUTH_ACCEPT_ANY: true` + `MP_SMTP_AUTH_ALLOW_INSECURE:
  true` — the capture sink accepts any credentials from relaying services.

## API Access

- **Base URL (loopback, unauthenticated at app layer):** `http://127.0.0.1:8025`
- **Base URL (edge, forward-auth gated):** `https://mail.<tenant_domain>`
- **API prefix:** `/api/v1/` (REST/JSON). No bot token — the API is open on the
  loopback UI port; the Authentik gate protects only the public edge.

## Health Check

- **Endpoint:** `GET /livez` (also `GET /readyz`).
- **Expected:** `200 OK`.
- The compose healthcheck runs `wget --spider http://127.0.0.1:8025/livez`.

## Dependencies

- None required to run (self-contained SQLite store).
- Authentik + Traefik provide the edge SSO gate (optional).
- Consumed by every mail-sending service in the estate as the SMTP relay target.
