# Device gateway

> Loopback BFF for handheld / phone / wearable callers. Sibling of Hermes as a
> host launchd daemon. Default-OFF. Authenticates Authentik RFC 8628 access
> tokens via loopback userinfo and proxies an allowlisted KEAP agent read.

## Quick Reference

| | |
|---|---|
| **Type** | Host organ (non-Docker), stdlib Python |
| **Domain** | `device.<tenant_domain>` (e.g. `device.pazny.eu`) |
| **Bind** | `127.0.0.1:8770` (`device_gateway_port`) |
| **Stack** | `host` |
| **Toggle** | `install_device_gateway: false` (default off) |
| **Manifest id** | `device_gateway` → node `service:device_gateway` (withheld) |
| **launchd label** | `eu.thisisait.nos.device-gateway` |
| **Runtime** | `~/device-gateway/gateway.py` (copied from SOURCE on converge) |
| **Logs** | `~/device-gateway/log/` |

Values from `roles/pazny.device_gateway/`, `files/anatomy/device-gateway/gateway.py`,
`terraform/authentik/device_gateway.tf`, `state/manifest.yml`.

## Why it is off by default

A LAN-open device BFF is a new processing of identifiers. The GDPR Art-30 row
(`device-gdpr-art30`) is an operator question — do not invent `legal_basis`.
There is no `device-gateway-base` plugin until that row is filled. This estate
may opt in via `config.yml`; forks stay off.

## Authentication

- **SSO bucket:** none at Traefik (`auth_mode: none`, ntfy class). A device has
  no browser session, so `authentik@file` is the wrong gate.
- **BFF auth:** `Authorization: Bearer` — loopback userinfo, then `azp`/`aud`
  must be `nos-device-gateway`.
- **RFC 8628:** public client `client_id=nos-device-gateway`, slug
  `device-gateway`. Verification URI is `https://auth.<tld>/device`. That page
  needs the default Authentik brand (`authentik-default`) marked `default: true`
  so it is not the in-memory `fallback` brand (empty HTTP 404).

## Allowlist

Allowlisted KEAP tables only (roadmap, current-state, todos-akadmin, repo,
application, package). `invoice` / `party` / `journal-entry` / `account` are 403.
Columns are projected. The seeder uses the slug as the KEAP table id; a
Face-created table keeps a UUID — the gateway then matches `title` (so
"nOS Roadmap" still serves `/tables/roadmap`). Pairing registry `device-client`
is schema-only on converge (`rows: []`); pair/unpair is runtime. Digest-device
/ iLEAPP is a different noun and is not this organ.

## Health

- **Loopback:** `GET http://127.0.0.1:8770/health` → `{"ok": true}`
- **Public:** `GET https://device.<tld>/health` (Traefik → host 8770)
