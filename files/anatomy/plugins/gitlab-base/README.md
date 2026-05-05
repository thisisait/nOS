# gitlab-base — service plugin (Track Q U5, Phase 1)

> **Status:** native-OIDC vessel landed 2026-05-04. Phase 2 C1 deletes the
> role-side `omniauth_*` lines inside `GITLAB_OMNIBUS_CONFIG` + the central
> `authentik_oidc_apps` row.

## What this carries

- `authentik:` block — `slug: gitlab`, `mode: native_oidc`,
  `redirect_uris: .../users/auth/openid_connect/callback`, tier 2 (manager).
- `compose_extension` — `GITLAB_OMNIBUS_CONFIG` with the omniauth DSL
  (gitlab_rails['omniauth_*']), mkcert CA mount under
  `/etc/gitlab/trusted-certs/`, and the authentik host-gateway alias.

## Mkcert CA conditional

The volume mount is gated on `install_authentik AND tenant_domain_is_local`.
Omnibus' update-ca-certificates wrapper picks up `trusted-certs/*.crt` at
boot — on a public TLD the system Mozilla list already validates LE
correctly.

## Two-writer caveat

Until Phase 2 C1, BOTH the role compose template and this fragment render
`GITLAB_OMNIBUS_CONFIG`. They render the SAME omniauth DSL, so the merged
env is byte-equivalent regardless of merge order. Phase 2 C1 removes the
role-side render so this plugin is the single writer.

## Defensive placeholder

`_NOS_PLUGIN: "gitlab-base"`.
