---
in_force: true
ruled: 2026-05-17
row: null
gates: []
---
# SSO — one mode per service

> Carved out of [`docs/sso-and-attribution.md`](../../docs/sso-and-attribution.md),
> which stays the guide: bucket membership, the attribution chain, the audit.

## 1. Four modes

Every service declares exactly one `authentik.mode` in its plugin
(`files/anatomy/plugins/<svc>-base/plugin.yml`):

| Mode | What it means | Unauthenticated `GET /` |
|---|---|---|
| `native_oidc` | The service speaks OIDC itself. Its own login page has a "Sign in with Authentik" button; each user's identity reaches the service. | 200 (own login) or 302 to its own login |
| `header_oidc` | Authentik's proxy outpost forwards `X-Authentik-*` headers; the service creates the local user from them. | 302 to Authentik |
| `forward_auth` | An access gate only. An Authentik session lets you in; the service keeps no per-user state. | 302 to Authentik |
| `none` | A substrate or a service with no SSO (PostgreSQL, Redis). | n/a |

The plugin is the record. Any list of which service sits in which mode is a
reading aid and can lag.

## 2. One spelling

`mode` and `provider_type` take one of the four values above. Anything else
(`oauth2`, `proxy_auth`, a missing mode) is refused, not defaulted.

## 3. Never gated twice

A `native_oidc` service is not also put behind `authentik@file`. That is a
second login to the same Authentik and it 302s machine callers. A 200 on a
`native_oidc` route is the service's own login page, not a bypass.

## 4. Tier means RBAC

Access tiers 1–4 bind to Authentik groups; each plugin sets `authentik.tier`.
The word `tier` means this and nothing else
([`layers.md`](layers.md) owns the dependency axis).
