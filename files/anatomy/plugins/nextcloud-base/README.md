# nextcloud-base — service plugin (Track Q U5, Phase 1)

> **Status:** native-OIDC vessel landed 2026-05-04. Phase 2 C1 deletes the
> central `authentik_oidc_apps` row.

## What this carries

- `authentik:` block — `slug: nextcloud`, `mode: native_oidc`,
  `post_setup: nextcloud_occ` (loader hands client_id/secret to `occ
  user_oidc:provider` via the role's post-tasks), tier 3 (user).
- `compose_extension` — mkcert CA mount conditional + authentik
  host-gateway alias. NO OIDC env vars (Nextcloud configures OIDC via
  `occ`, not env).

## Mkcert CA conditional

Volume mount gated on `install_authentik AND tenant_domain_is_local`. The
Nextcloud base image runs `update-ca-certificates` at boot so the mkcert CA
ends up in PHP curl's trusted bundle — needed for the `occ user_oidc:provider`
discovery call against the local-TLD Authentik endpoint.

## Why no OIDC env block

Nextcloud's `user_oidc` app is configured via the `occ` CLI (DB-backed),
not env vars. The role's `tasks/post.yml` runs `occ user_oidc:provider add`
with the credentials from `authentik_oidc_nextcloud_*` (today derived from
the central list). Phase 2 C1: loader's authentik aggregator emits these
directly from this plugin's `authentik:` block; the role's post-task reads
from the loader's resolved values.

## Defensive placeholder

`_NOS_PLUGIN: "nextcloud-base"`.
