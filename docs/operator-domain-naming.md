# Operator guide — domain naming (Track F)

> Three variables compose every nOS hostname. Defaults reproduce the
> pre-Track-F flat layout; `host_alias` slots a per-host segment for
> multi-instance / fleet deploys.
>
> Status: **Track F (2026-05-01)** • shim: `instance_tld` still works through
> Q3 2026 then will be removed.

---

## TL;DR

```yaml
# config.yml (defaults shown)
tenant_domain: dev.local        # the TLD; everything resolves under it
host_alias: ""                  # "" drops the segment; "lab" yields bone.lab.dev.local
apps_subdomain: apps            # subdomain segment for Tier-2 apps stack
```

| Setting | Tier-1 host (e.g. `bone`) | Tier-2 app (e.g. `documenso`) |
|---|---|---|
| Default (host_alias `""`) | `bone.dev.local` | `documenso.apps.dev.local` |
| `host_alias: "lab"` | `bone.lab.dev.local` | `documenso.lab.apps.dev.local` |
| `tenant_domain: "pazny.eu"` | `bone.pazny.eu` | `documenso.apps.pazny.eu` |
| `tenant_domain: "pazny.eu"` + `host_alias: "lab"` | `bone.lab.pazny.eu` | `documenso.lab.apps.pazny.eu` |

---

## Composition rules

The resolved FQDN is built as:

```
Tier-1:  <svc>[.<host_alias>].<tenant_domain>
Tier-2:  <svc>[.<host_alias>].<apps_subdomain>.<tenant_domain>
```

The `host_alias` slot is **dropped entirely** when empty (no orphan dot).
The Phase-2 helper `_host_alias_seg` yields `".lab"` (with leading dot) when
set or `""` when empty — consumer templates use it as
`<svc>{{ _host_alias_seg }}.{{ tenant_domain }}`.

### What lives where

| Var | What it is | When to change |
|---|---|---|
| `tenant_domain` | The TLD all services live under | Once per box / fleet — `dev.local` for local dev, `pazny.eu` (or your real domain) for prod |
| `host_alias` | Optional per-host segment | When deploying multiple boxes against the same `tenant_domain` (lab / factory / branch) and you want them all reachable as `*.lab.pazny.eu` / `*.factory.pazny.eu` |
| `apps_subdomain` | Tier-2 app subdomain | Rarely — defaults to `apps` so Tier-2 (`documenso`, `roundcube`, ...) stays out of Tier-1 routing (`grafana`, `gitea`, ...) |

---

## Migrating from `instance_tld`

If your `config.yml` still has the legacy variable:

```yaml
# Before (pre-Track-F):
instance_tld: pazny.eu
```

The playbook auto-promotes this at run time and prints a deprecation
warning. **No action required for the upgrade to land green** — every
service keeps resolving correctly because the auto-promote runs in
`pre_tasks` before any role evaluates `tenant_domain`.

To clear the warning, rename the key at your convenience:

```yaml
# After (Track F):
tenant_domain: pazny.eu
# host_alias: ""                      # optional per-host segment
```

The `instance_tld` shim still resolves correctly via Jinja substitution
when **only `tenant_domain` is set** — but if both are present and
disagree, your explicit `tenant_domain` wins. Defining only one (the new
one) is the cleanest end state.

---

## Cert behaviour

The cert-zone apex follows the wildcard scope:

| Config | Cert SANs (mkcert / ACME) | Cert filename |
|---|---|---|
| Default | `*.dev.local`, `*.apps.dev.local` (+ `*.os.dev.local` if Puter) | `acme/dev.local.crt` |
| `host_alias: "lab"` | `*.lab.dev.local`, `*.lab.apps.dev.local` | `acme/lab.dev.local.crt` |
| `tenant_domain: "pazny.eu"` | `*.pazny.eu`, `*.apps.pazny.eu` | `acme/pazny.eu.crt` |

The cert filename uses the **wildcard zone apex** (`host_alias.tenant_domain`
when alias is set, else `tenant_domain`). Multiple `host_alias` deploys
against the same `tenant_domain` get separate cert files so they don't
overwrite each other if you ever swap config.yml between them.

For local-TLD deploys (`*.local`, `*.lan`, `*.test`, `*.localhost` —
detected via `tenant_domain_is_local`), mkcert generates the wildcard
cert directly into `tls/local-dev.crt`. ACME is auto-disabled.

For public-TLD deploys, ACME (Cloudflare DNS-01) issues the wildcard
when `acme_cloudflare_api_token` is set in `credentials.yml`.

---

## Cookie domain (Authentik SSO)

`AUTHENTIK_COOKIE_DOMAIN` scopes the SSO cookie:

| Config | Cookie domain | Effect |
|---|---|---|
| Default | `.dev.local` | All `*.dev.local` services share the SSO session |
| `host_alias: "lab"` | `.lab.dev.local` | Cookie scoped to `*.lab.dev.local` only — multiple host_alias deploys on the same `tenant_domain` stay isolated |

This is automatic — you don't override it directly.

---

## Email FROM addresses

Service-generated emails (`gitea@...`, `outline@...`, `authentik@...`,
admin notifications) use:

```
<svc>@<tenant_domain>
```

**No `host_alias` segment** — emails stay tenant-scoped so a fleet of
`lab` / `factory` / `branch` boxes all send recognizably from the same
domain. Override per-service via `<svc>_email_from` (where available)
if you want box-scoped sender addresses.

---

## When NOT to set `host_alias`

- **Single-box deploy**: leave it empty. The flat layout
  (`bone.dev.local`, `gitea.dev.local`, …) is shorter and easier to type.
- **Multi-box deploy with separate TLDs**: each box gets its own
  `tenant_domain` (e.g. `lab.pazny.eu`, `factory.pazny.eu`); leave
  `host_alias` empty on all of them.

## When to set `host_alias`

- **Multi-box fleet on a single TLD**: each box keeps the same
  `tenant_domain` (`pazny.eu`) and sets a unique `host_alias` (`lab`,
  `factory`, `branch`). Cookie domains stay isolated, cert SANs match
  the wildcard zone, no cross-box session bleed.
- **Local dev with named environments**: useful when you run `dev.local`
  and `staging.local` in parallel and want them coexisting on the same
  workstation under one cert tree (`tenant_domain: dev.local` +
  `host_alias: staging` ⇒ `*.staging.dev.local`).

---

## Reference

- Phase plan + commit log: see Track F entries in
  [`docs/roadmap-2026q2.md`](roadmap-2026q2.md)
- Authoritative variable definitions:
  [`default.config.yml`](../default.config.yml) lines 11–80
- Auto-promote pre-task:
  [`main.yml`](../main.yml) `[Track F compat]` block in `pre_tasks`
- FQDN composition helpers:
  - `_host_alias_seg` — segment string with leading dot (or empty)
  - `_acme_zone` — wildcard apex for cert filenames
  - Tier-2 expansion: `library/nos_apps_render.py:_fqdn_for()` +
    `module_utils/nos_app_parser.py:resolve_tokens()`
