# n8n-base — service plugin (Track Q U5, Phase 1)

> **Status:** native-OIDC vessel landed 2026-05-04. Phase 2 C1 deletes
> the role-side N8N_AUTH_OIDC_* block + the central authentik_oidc_apps row.

## What this carries

- `authentik:` block — `slug: n8n`, mode `native_oidc`, two redirect URIs
  (`/rest/oauth2-credential/callback` + `/rest/oidc/callback`), tier 2 (manager).
- `compose_extension` — `N8N_AUTH_OIDC_ENABLED/CLIENT_ID/CLIENT_SECRET/ISSUER`
  + `N8N_AUTH_OIDC_ALLOWED_GROUPS` (empty = allow all), mkcert CA volume +
  `NODE_EXTRA_CA_CERTS` env, `extra_hosts authentik:host-gateway`.

## Mkcert CA conditional

n8n's mkcert CA mount is gated only on `tenant_domain_is_local`, not on
`install_authentik` — n8n itself uses `NODE_EXTRA_CA_CERTS` for outbound
HTTPS to user-defined integrations, independent of SSO. Mirrors the live
role template's shape.

## Defensive placeholder

`_NOS_PLUGIN: "n8n-base"`.
