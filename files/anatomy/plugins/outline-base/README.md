# outline-base — service plugin (Track Q U5, Phase 1)

> **Status:** native-OIDC vessel landed 2026-05-04. Both this plugin's
> compose-extension and the role-side env block render today (idempotent
> overlay). Phase 2 C1 deletes the central `authentik_oidc_apps` row +
> the role-side OIDC env block, leaving this manifest as the single source
> of truth.

## What this carries

- `authentik:` block — replaces `authentik_oidc_apps[slug=outline]` once
  the loader aggregator lands.
- `compose_extension` — Outline's `OIDC_*` env vars + mkcert CA volume
  conditional + `extra_hosts authentik:host-gateway`.
- Tier 3 (user) per `authentik_app_tiers`.

## Mkcert CA conditional

`{% if install_authentik | default(false) and (tenant_domain_is_local | default(true) | bool) %}` gates BOTH the `rootCA.pem` volume mount AND
the matching `NODE_EXTRA_CA_CERTS` env var, so a public-TLD deploy doesn't
shadow the system Mozilla CA list and break Authentik LE chain validation.
Same regression class closed across 14 roles 2026-05-03.

## Defensive placeholder

`_NOS_PLUGIN: "outline-base"` — guarantees `environment:` renders a valid
YAML mapping when all conditional blocks render empty (`install_authentik=false`).
Per P0.12 doctrine.
