# open-webui-base — service plugin (Track Q U5, Phase 1)

> **Status:** native-OIDC vessel landed 2026-05-04. Idempotent overlay
> alongside the role-side compose template. Phase 2 C1 deletes the role-
> side OAUTH_* env block + the central `authentik_oidc_apps` row.

## What this carries

- `authentik:` block — `slug: open-webui`, `mode: native_oidc`,
  `redirect_uris: .../oauth/oidc/callback`, tier 3 (user).
- `compose_extension` — `OAUTH_CLIENT_ID/SECRET`, `OPENID_PROVIDER_URL`
  discovery URL, `OAUTH_MERGE_ACCOUNTS_BY_EMAIL`, `OAUTH_SCOPES`, plus
  `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` / `AIOHTTP_*_SSL` (Python httpx)
  gated on `tenant_domain_is_local`, plus mkcert CA volume mount on
  the same gate, plus `extra_hosts authentik:host-gateway`.

## Mkcert CA conditional

Open WebUI was the role that surfaced the regression class on 2026-05-03.
This plugin preserves the same gate shape: local TLDs get the mkcert CA
bundle; public TLDs use the system Mozilla list to validate Authentik LE
certs.

## Defensive placeholder

`_NOS_PLUGIN: "open-webui-base"` keeps `environment:` valid when
`install_authentik=false`.
