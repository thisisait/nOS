# Grafana wiring inventory — A6.5 doctrine PoC artifact

> **Status:** research artifact, captured 2026-05-03 by claude+pazny.
> **Purpose:** prove §1.1 thin-role doctrine on Grafana before generalizing
> via Track Q. This inventory is the input to `role-thinning-recipe.md` and
> the draft `plugins/grafana-base/plugin.yml`.

## TL;DR

Today's `roles/pazny.grafana/` totals **396 lines** across 6 files. Cross-cutting
wiring scattered outside the role accounts for **~880 additional lines** across
**11 surfaces** (default.config.yml, core-up.yml, observability.yml, files/observability/grafana/,
state/manifest.yml, service-registry.json.j2, …).

After thin-role + grafana-base plugin extraction:
- **Role:** ~140 lines (defaults + thin tasks/main.yml + compose template stripped of OIDC + meta + handlers)
- **Plugin:** ~600 lines (manifest + 17 dashboards as data, datasource provisioning, OIDC wiring spec, post-hook for admin password)
- **Net change:** roughly LOC-neutral but **architectural locality dramatically improves** — every Grafana concern lives in two paths (`roles/pazny.grafana/` for skeleton, `files/anatomy/plugins/grafana-base/` for body) instead of 11.

Real LOC win comes in Track Q follow-on batches (Q1 alone removes ~300 lines from
`tasks/stacks/core-up.yml` once observability provisioning all moves to plugins).

---

## Surfaces inventoried

### 1. Role internals — `roles/pazny.grafana/` (396 lines)

| File | Lines | Verdict | Reason |
|---|---:|---|---|
| `defaults/main.yml` | 19 | **STAYS** (skeleton) | version, port, data_dir, mem_limit — install-internal |
| `tasks/main.yml` | 29 | **STAYS** (already thin) | data dir + compose render — exactly the doctrine target |
| `templates/compose.yml.j2` | 274 | **SPLIT** | base service def stays (~150 lines); OIDC env block (~25 lines) + plugin install env (~3 lines) move to plugin-emitted secondary override |
| `tasks/post.yml` | 44 | **STAYS** (debatable; see EC2 below) | `grafana-cli admin reset-admin-password` — install-internal admin state, no cross-service coupling |
| `handlers/main.yml` | 10 | **STAYS** | restart handler |
| `meta/main.yml` | 20 | **STAYS** | role metadata |

### 2. Provisioning — `files/observability/grafana/` (~430 lines + 17 dashboards)

| File | Verdict | Reason |
|---|---|---|
| `provisioning/datasources/all.yml.j2` | **MOVES to plugin** | declares Prometheus + Loki + Tempo + sqlite + postgres datasources — pure cross-service wiring |
| `provisioning/dashboards/all.yml.j2` | **MOVES to plugin** | dashboard provider config |
| `provisioning/dashboards/00-home.json … 99-playbook.json` (17 files) | **MOVES to plugin** | dashboards are *data*, not install state |

### 3. Provisioning task wiring — `tasks/stacks/core-up.yml` (~50 lines)

| Lines | What | Verdict |
|---|---|---|
| 74-76 | Create `~/observability/grafana/provisioning/{datasources,dashboards}` dirs | **MOVES** to plugin loader (lifecycle: pre-compose) |
| 133-134 | Stat config files | **MOVES** (verification step) |
| 236-239 | `include_role: pazny.grafana` | **STAYS** (role still installs the binary) |
| 304-310 | Deploy datasources `all.yml.j2` template | **MOVES** to plugin loader |
| 312-318 | Deploy dashboards provisioning config | **MOVES** to plugin loader |
| 437-442 | Grafana admin password reconverge include | **STAYS** (role-internal post-step) |

### 4. Provisioning task wiring — `tasks/observability.yml` (~50 lines)

| Lines | What | Verdict |
|---|---|---|
| 217-225 | Download community Grafana dashboards from grafana.com (loop over `grafana_dashboards`) | **MOVES** to plugin (or to a separate `grafana-community-dashboards` plugin if operator wants opt-in) |
| 229-235 | Enumerate in-repo dashboards | **MOVES** |
| 237-247 | Deploy in-repo dashboards to runtime dir | **MOVES** |
| 249-251 | Nginx vhost symlink (legacy fallback path) | **STAYS in tasks/nginx.yml fallback** — gated on `install_nginx: true` already; not Grafana-specific concern |

### 5. Identity wiring — `default.config.yml`

| Block | Verdict |
|---|---|
| `authentik_oidc_apps` entry for grafana (slug, client_id, client_secret, redirect_uris, launch_url) — 8 lines | **MOVES to plugin** (plugin's `authentik:` section becomes source of truth) |
| Derived `authentik_oidc_grafana_client_id` + `_client_secret` (2 lines) | **REMOVED** — replaced by plugin loader resolving from manifest |

### 6. Compose-level identity env — `roles/pazny.grafana/templates/compose.yml.j2`

The compose template currently contains 19 `GF_AUTH_GENERIC_OAUTH_*` env vars
plus 1 `GF_AUTH_SIGNOUT_REDIRECT_URL`. **All 20 lines move to a plugin-emitted
secondary compose override** (`{{ stacks_dir }}/observability/overrides/grafana-base.yml`).

This is the single biggest doctrinal challenge — see edge-case EC1 below.

### 7. Service catalog — `state/manifest.yml`

Grafana's row in `state/manifest.yml` (~17 lines) **STAYS at top-level**. The
manifest is the platform-wide service catalog (used by Traefik file-provider,
Wing /hub, smoke tests). Plugins do not own the catalog; they extend it via
`discoverable_plugins.yml` (post-PoC API, post-Track-Q maybe).

The `oidc: native` field is fine — it states Grafana speaks OIDC natively (vs.
proxy-auth services). This is a service property, not a plugin property.

### 8. Wing/Hub UI — `templates/service-registry.json.j2`

Hardcoded `grafana` stanza (~10 lines). **STAYS for now**; long-term replaced by
plugin loader emitting registry entries.

### 9. Final summary — `tasks/final-summary.yml`

One-line URL print for Grafana admin login. **STAYS** (this is summary output,
not wiring).

### 10. Coexistence support — `tasks/coexistence-*.yml` + manifest's `coexistence_supported: true`

Coexistence framework (Wave-2 dual-version operation) treats Grafana as a
first-class citizen. **Coexistence stays in the framework**, but the version-pin
override that coexistence emits should consult plugin compose fragments too. Edge
case for Track Q sweep — not blocker for A6.5.

### 11. Coolify importer + Tier-2 — N/A for grafana

Grafana is Tier-1, not in the apps_runner orbit. Doctrine for Tier-2 manifests
is the same shape (plugins wire to apps), but Track Q's first batches focus on
Tier-1.

---

## Edge cases discovered

### EC1: Compose template OIDC env block (biggest)

Today's `roles/pazny.grafana/templates/compose.yml.j2` has Authentik env vars
*inside* the role's compose template. The role thus knows about Authentik.

**Resolution:** plugin loader writes a SECOND override fragment under
`{{ stacks_dir }}/observability/overrides/grafana-base.yml` containing the
OIDC env block. Docker Compose's multi-`-f` merge already supports this
(`tasks/stacks/core-up.yml` discovers all `overrides/*.yml` and passes them
as `-f` flags).

**Pattern (post-Track-Q):**
```yaml
# roles/pazny.grafana/templates/compose.yml.j2 — knows ZERO about Authentik
services:
  grafana:
    image: grafana/grafana-oss:{{ grafana_version }}
    environment:
      GF_SERVER_DOMAIN: "{{ grafana_domain }}"
      GF_SERVER_ROOT_URL: "https://{{ grafana_domain }}"
      # NO GF_AUTH_*, NO GF_INSTALL_PLUGINS — both moved to plugin

# files/anatomy/plugins/grafana-base/templates/grafana-base.compose.yml.j2 — emitted by loader
services:
  grafana:
    environment:
      GF_AUTH_GENERIC_OAUTH_ENABLED: "true"
      GF_AUTH_GENERIC_OAUTH_CLIENT_ID: "{{ plugin.authentik.client_id }}"
      # ...
```

This is the **canonical "vessel" pattern** — plugin contributes a compose
fragment that gets merged into the running stack. **Generalizes to**:
- alloy-scrape plugin contributes scrape entries to a generated `scrape-config.yml`
- service-X-postgres plugin contributes a `postgres-init` migration that runs
  before service X's compose-up
- mailpit-relay plugin contributes SMTP env vars to every service's compose
  override that opts into `requires.notifier: mail`

### EC2: post.yml admin password reconverge — role or plugin?

**Argument for role:** it's about Grafana admin user state, no other service
involved. No cross-cutting wiring.

**Argument for plugin:** it's a post-compose hook — plugin loader needs
post-hooks anyway (for `POST /api/plugins/grafana/dashboards`, etc.).

**Verdict for A6.5:** **STAYS in role** because (a) doctrine says role owns
install + install-internal-state, (b) admin-password-reset is exactly that,
(c) plugin loader gets enough post-hook surface from dashboards/datasources/
gdpr-row anyway.

If a future plugin needs to reset admin password (e.g. `grafana-rotate-admin`
plugin), it composes the existing role hook — fine.

### EC3: `frser-sqlite-datasource` plugin install via `GF_INSTALL_PLUGINS`

Currently in role compose (gated on `install_wing | default(false)`). It's
there because the **wing-grafana composition** (Wing's SQLite tables visible
in Grafana dashboards) requires it.

**Doctrine resolution:** This is a **composition plugin** concern. Move
`GF_INSTALL_PLUGINS=frser-sqlite-datasource` out of the role's compose template;
add it to a `wing-grafana` composition plugin's emitted fragment. Activates
ONLY when `install_wing: true` AND `install_observability: true`.

A6.5 PoC scope: park this — keep the conditional in the role for now, refactor
in Q1 (observability batch) once composition plugins are operator-validated.

### EC4: `tasks/observability.yml` mixes Alloy + Grafana

Today's file is one long script doing Alloy install + community dashboard
download + in-repo dashboard deploy. After A6.5 the Grafana parts move out;
the Alloy parts stay until Q1 (alloy thinning). **Result:** A6.5 leaves
~25 lines of pure-Alloy logic; Q1 collapses that further.

### EC5: Plugin loader needs lifecycle hooks

The plugin loader can't just "fire and forget" — Grafana provisioning must
land BEFORE `docker compose up observability`. Required hooks:

| Hook | Fires | Used by |
|---|---|---|
| `pre-render` | Before any role render | Plugin can declare needed dirs |
| `pre-compose` | After role render, before `docker compose up <stack>` | Plugin emits compose-extension fragments + provisioning files |
| `post-compose` | After `docker compose up <stack> --wait` | Plugin runs API calls (POST dashboards, register OIDC, etc.) |
| `post-blank` | At blank-reset time | Plugin cleans plugin-owned data |

Phase A6 (plugin-system) must implement all four. **A6.5 validates them on
Grafana before Q1 generalizes.**

### EC6: One-pass migration vs. dual-emit during transition

Two strategies:

- **(a) Big-bang one-pass:** single commit removes role env + adds plugin.
  Simpler. Atomic. Bisectable. **Recommended for A6.5.**
- **(b) Dual-emit:** role gets `grafana_use_external_oidc_wiring: false`
  default; when plugin activates, sets to true and role drops env block.
  Useful for Q-track if operator wants per-role rollout. **NOT needed for
  A6.5** because PoC blank is acceptable.

### EC7: `_host_alias_seg` + `tenant_domain` access in plugin context

Plugin manifest contains Jinja that references these vars. Loader must pass
them. Trivial — loader is an Ansible task that already sees all role vars.
Documented in plugin loader spec (§6.4).

### EC8: Backwards-compat for migration recipes / coexistence framework

`migrations/2026-XX-grafana-thin-role.yml` (Q-track) needs a non-blank-required
migration path for hosts that already deployed Grafana the old way. PoC blank
side-steps this. Q1 will need a real migration step that:

1. detects role's old shape (compose has `GF_AUTH_*`)
2. re-renders role's compose without OIDC
3. invokes plugin loader to emit new fragment
4. `docker compose up grafana --no-deps` to restart with merged config
5. verifies OIDC login still works (Authentik probe)

That migration is ~30 lines and reusable for every Q-batch role.

---

## What this inventory tells us about the doctrine

1. **Role thinning IS achievable** — 396-line role becomes ~140-line role with
   no functional regression, all wiring relocated.
2. **The "vessel" pattern is the key invention** — plugin emits compose
   fragments that merge into the stack alongside the role's compose. Without
   it, OIDC env can't escape the role template.
3. **Plugin loader needs 4 lifecycle hooks** (pre-render, pre-compose,
   post-compose, post-blank) — not just one "register everything" pass.
4. **Composition plugins matter from day 1** — the `frser-sqlite-datasource`
   case proves them. Even PoC scope can't fully escape them; we just defer
   the activation logic to Q1.
5. **Grafana is a representative target.** Authentik (much denser OIDC
   wiring), Outline (DB + OIDC + storage), Bluesky PDS (unique federation
   wiring) will each surface 1-2 new edge cases. But the recipe + 4 lifecycle
   hooks + vessel pattern from A6.5 should cover ~80% of Q-track work.

---

## Forward references

- Plugin manifest draft: `files/anatomy/plugins/grafana-base/plugin.yml`
- Recipe (deterministic 6-step process): `files/anatomy/docs/role-thinning-recipe.md`
- Doctrine source: `docs/bones-and-wings-refactor.md` §1.1
