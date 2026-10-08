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
Nextcloud base image does NOT run `update-ca-certificates` (#53), so the same
guard overrides the entrypoint: rebuild the store, then `exec /entrypoint.sh
apache2-foreground`. That puts the mkcert CA in PHP curl's trust — needed for
user_oidc's discovery and token calls against the local-TLD Authentik.
Gate: `tests/anatomy/test_mkcert_ca_mount_is_trusted.py`.

## Why no OIDC env block

Nextcloud's `user_oidc` app is configured via the `occ` CLI (DB-backed),
not env vars. The role's `tasks/post.yml` runs `occ user_oidc:provider add`
with the credentials from `authentik_oidc_nextcloud_*` (today derived from
the central list). Phase 2 C1: loader's authentik aggregator emits these
directly from this plugin's `authentik:` block; the role's post-task reads
from the loader's resolved values.

## Defensive placeholder

`_NOS_PLUGIN: "nextcloud-base"`.
