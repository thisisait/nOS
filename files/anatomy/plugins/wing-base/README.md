# wing-base — proxy-auth plugin (Q2 batch)

> **Status:** live, captured 2026-05-04. Wires `pazny.wing` into the
> Authentik forward-auth doctrine via Traefik middleware. Tier 1
> (admin) per CLAUDE.md RBAC mapping.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Authentik forward-auth binding | `authentik.mode: forward_auth` | No native OIDC — gate is at Traefik layer |
| RBAC tier | `authentik.tier: 1` | Maps to `nos-admins` group + above |
| Traefik labels | `compose_extension.template` | `authentik@file` middleware applied |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention -1d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point |

## What stays in the role

`roles/pazny.wing/` keeps install-only responsibilities — image pin, port
defaults, data dir, base compose fragment. This plugin layers proxy-
auth wiring on top via a secondary compose override merged by the
existing override-discovery loop in `core-up.yml` / `stack-up.yml`.

## Forward-auth vs. native OIDC

Per CLAUDE.md "Forward-auth vs. native-OIDC SSO" gotcha:

> Services with `200 OK` on Traefik route are NOT bypassing SSO — they
> have native OIDC with their own login page that surfaces a "Sign in
> with Authentik" button. Forward-auth (Traefik middleware
> `authentik@file`) is used for services WITHOUT app-level OIDC support.

`wing` is in the second bucket — Authentik enforces login at the
proxy layer; the service trusts the upstream session header.


## Gotcha — Wing is a host-mode daemon, not a Docker service

As of anatomy A3.5 (2026-05-04) Wing runs as `eu.thisisait.nos.wing`
launchd daemon backed by FrankenPHP. The compose template here
renders an empty `services: {{}}` block — Traefik routes `wing.<tld>`
to `http://nos-host:{{{{ wing_port }}}}` via the file-provider's host-
mode path (state/manifest.yml drives it).


## Smoke

```
PYTHONPATH=files/anatomy python3 -m module_utils.load_plugins smoke \
    --root files/anatomy/plugins
```

Plugin must report `ok` for `wing-base`.
