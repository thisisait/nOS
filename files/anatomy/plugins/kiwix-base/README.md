# kiwix-base — proxy-auth plugin (Q2 batch)

> **Status:** live, captured 2026-05-04. Wires `pazny.kiwix` into the
> Authentik forward-auth doctrine via Traefik middleware. Tier 4
> (guest) per CLAUDE.md RBAC mapping.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Authentik forward-auth binding | `authentik.mode: forward_auth` | No native OIDC — gate is at Traefik layer |
| RBAC tier | `authentik.tier: 4` | Maps to `nos-guests` group + above |
| Traefik labels | `compose_extension.template` | `authentik@file` middleware applied |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention 90d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point |

## What stays in the role

`roles/pazny.kiwix/` keeps install-only responsibilities — image pin, port
defaults, data dir, base compose fragment. This plugin layers proxy-
auth wiring on top via a secondary compose override merged by the
existing override-discovery loop in `core-up.yml` / `stack-up.yml`.

## Forward-auth vs. native OIDC

Per CLAUDE.md "Forward-auth vs. native-OIDC SSO" gotcha:

> Services with `200 OK` on Traefik route are NOT bypassing SSO — they
> have native OIDC with their own login page that surfaces a "Sign in
> with Authentik" button. Forward-auth (Traefik middleware
> `authentik@file`) is used for services WITHOUT app-level OIDC support.

`kiwix` is in the second bucket — Authentik enforces login at the
proxy layer; the service trusts the upstream session header.



## Smoke

```
PYTHONPATH=files/anatomy python3 -m module_utils.load_plugins smoke \
    --root files/anatomy/plugins
```

Plugin must report `ok` for `kiwix-base`.
