# freescout-base

Service plugin for FreeScout helpdesk under nOS. Wires Authentik SSO via
the [freescout-oauth](https://github.com/freescout-helpdesk/freescout/wiki/Modules)
community module, configured by `FREESCOUT_OIDC_*` environment variables.

## Tier

**2 (manager)** — helpdesk staff handle customer support. Customer
data exposure is significant; only confirmed agents reach the UI.

## What this plugin does

- Renders a compose extension at `{{ stacks_dir }}/b2b/overrides/freescout-base.yml`
  carrying the OIDC env block + the mkcert CA mount conditional + the
  `extra_hosts` host-gateway alias for Authentik discovery.
- Declares the Authentik OIDC client.
- Declares the GDPR Article 30 row (legitimate_interests; **3-year retention**
  matching typical helpdesk-data horizons).
- Provides the Wing `/hub` deep-link card.

## Status

Ships in Phase 1 mop-up (2026-05-05). U8 worker had this scoped as
`native_oidc_api` (artisan CLI), but the role already wires OIDC purely
through env vars — env-based fits U5/U6 shape cleanly.

## Health

`https://{{ freescout_domain }}/` — 200 OK once container is up; SSO
button surfaces after Authentik bootstraps.
