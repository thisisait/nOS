# puter-base — proxy-auth plugin (Q2 batch)

> **Status:** live, captured 2026-05-04. Wires `pazny.puter` into the
> Authentik forward-auth doctrine via Traefik middleware. Tier 3
> (user) per CLAUDE.md RBAC mapping.

## What this plugin owns

| Surface | Block | Notes |
|---|---|---|
| Authentik forward-auth binding | `authentik.mode: forward_auth` | No native OIDC — gate is at Traefik layer |
| RBAC tier | `authentik.tier: 3` | Maps to `nos-users` group + above |
| Traefik labels | `compose_extension.template` | `authentik@file` middleware applied |
| GDPR Article 30 row | `gdpr:` | `legitimate_interests`, retention -1d |
| Wing /hub deep-link card | `ui-extension.hub_card` | Operator entry point |

## What stays in the role

`roles/pazny.puter/` keeps install-only responsibilities — image pin, port
defaults, data dir, base compose fragment. This plugin layers proxy-
auth wiring on top via a secondary compose override merged by the
existing override-discovery loop in `core-up.yml` / `stack-up.yml`.

## Forward-auth vs. native OIDC

Per CLAUDE.md "Forward-auth vs. native-OIDC SSO" gotcha:

> Services with `200 OK` on Traefik route are NOT bypassing SSO — they
> have native OIDC with their own login page that surfaces a "Sign in
> with Authentik" button. Forward-auth (Traefik middleware
> `authentik@file`) is used for services WITHOUT app-level OIDC support.

`puter` is in the second bucket — Authentik enforces login at the
proxy layer; the service trusts the upstream session header.


## Note — Puter has both an OS domain and an API domain

`puter_domain` is the OS frontend; `puter_api_domain` (api.os.<tld>)
is the JSON API. This plugin gates the OS frontend; the API domain
is left ungated because Puter speaks its own session token over JSON.


## Smoke

```
PYTHONPATH=files/anatomy python3 -m module_utils.load_plugins smoke \
    --root files/anatomy/plugins
```

Plugin must report `ok` for `puter-base`.
