# Authentik wiring inventory — Track Q Q2 prep + doctrine validation

> **Status:** research artifact, captured 2026-05-03 by claude+pazny.
> **Purpose:** validate §1.1 doctrine on a **second** role, this time the
> OIDC source-of-truth (vs. Grafana's OIDC consumer shape). Surfaces edge
> cases specific to "platform" services that aren't visible from a single
> consumer-side inventory.

## Why Authentik as the second target

Grafana taught us the **consumer pattern**: a service receives OIDC config
from Authentik, gets dashboards provisioned, gets scrape entries. Wiring
points one direction (Authentik → consumer).

Authentik is the **source pattern**: the service IS the OIDC root. Consumer
plugins (`grafana-base`, `outline-base`, `nextcloud-base`, …) reach back to
Authentik. The inventory must answer: **what stays in `authentik-base`
plugin vs. what stays in each consumer plugin's `authentik:` block?**

Answering this clarifies the **dependency direction** in the plugin graph,
which is doctrine-critical: wrong direction = circular plugin dependencies.

## TL;DR

Today's `roles/pazny.authentik/` totals **187 lines** (role) + **408 lines**
of supporting tasks outside the role (blueprints.yml, health.yml,
authentik_service_post.yml, authentik-migrate.yml) + **347 lines** of
blueprint templates. **~942 lines of Authentik-touching code in the
mainline repo, ~80% of which is wiring rather than install.**

`default.config.yml` carries **123 `name:` entries** total — most are
inside `authentik_oidc_apps` (the central registry of OIDC consumers). This
list is the **single biggest scattered-wiring artifact in the repo**.

After thin-role + plugin extraction:

- **`pazny.authentik` role:** ~70 lines (defaults + thin tasks/main.yml +
  compose template stripped of *blueprint orchestration* + meta).
- **`authentik-base` plugin (source plugin):** ~250 lines (manifest +
  blueprints/ subdirectory with the 4 templates moved + lifecycle hook for
  blueprint apply + GDPR row + observability self-metrics).
- **Per-consumer plugins (already in scope of Track Q):** each consumer
  plugin (`grafana-base`, `outline-base`, …) carries its own `authentik:`
  block (already in `grafana-base/plugin.yml`). The `authentik_oidc_apps`
  list in `default.config.yml` **disappears entirely** — replaced by
  loader-side aggregation of consumer plugin `authentik:` blocks.

**This is the biggest LOC reduction the doctrine produces.** Track Q Q2
(IAM batch) is projected at **-800 to -1100 lines net** just from
authentik thinning + the disappearance of `authentik_oidc_apps` + derived
`authentik_oidc_*_client_id`/`_client_secret` vars.

---

## Surfaces inventoried

### 1. Role internals — `roles/pazny.authentik/` (187 lines + 347 blueprint lines)

| File | Lines | Verdict | Reason |
|---|---:|---|---|
| `defaults/main.yml` | 31 | **STAYS** | version, port, DB connection params — install-internal |
| `tasks/main.yml` | 30 | **STAYS** | data dir + compose render |
| `tasks/blueprints.yml` | 50 | **MOVES to plugin** | renders 4 blueprint files → bind-mount path; pure wiring |
| `tasks/health.yml` | 51 | **MOVES to plugin lifecycle.post_compose** | readiness probe; not install |
| `templates/compose.yml.j2` | 126 | **STAYS** | server + worker compose def — install-internal |
| `templates/blueprints/00-admin-groups.yaml.j2` | 87 | **MOVES** | RBAC groups list — depends on `authentik_rbac_tiers` (config-driven) |
| `templates/blueprints/10-oidc-apps.yaml.j2` | 108 | **MOVES + REPLACED** | this is the consumer aggregator — see SR-1 below |
| `templates/blueprints/20-rbac-policies.yaml.j2` | 52 | **MOVES** | tier policy bindings |
| `templates/blueprints/30-agent-clients.yaml.j2` | 100 | **MOVES** | agent OAuth2 clients (Track B) |
| `meta/main.yml` | ~20 | **STAYS** | role metadata |
| `handlers/main.yml` | ~10 | **STAYS** | restart handler |

### 2. Outside-role tasks (408 lines)

| File | Lines | Verdict |
|---|---:|---|
| `tasks/stacks/authentik_service_post.yml` | 184 | **MOVES to plugin lifecycle.post_compose** — service-side OIDC client setup, outpost binding (today owned by no role; pure wiring) |
| `tasks/authentik-migrate.yml` | 123 | **STAYS at top-level** (or moves under `migrations/`) — handles legacy Authentik instance migration; not plugin-scoped |
| `tasks/stacks/bluesky_pds_bridge.yml` | (already split) | **STAYS** — referenced from authentik but is its own concern (PDS bridge) |

### 3. Top-level config — `default.config.yml`

| Block | Verdict |
|---|---|
| `authentik_oidc_apps:` (the entire list — currently the single biggest cross-service artifact) | **DISAPPEARS as a list**. Each consumer plugin (`grafana-base`, etc.) carries its own `authentik:` block. Plugin loader aggregates them at hook 1 (pre_render) and emits the merged blueprint stream. **This is SR-1 below.** |
| `authentik_oidc_<svc>_client_id` / `_client_secret` derived vars (one pair per consumer service) | **REMOVED** — loader resolves at apply time from plugin manifests |
| `authentik_rbac_tiers:` (group definitions) | **MOVES to `authentik-base` plugin** |
| `authentik_app_tiers:` (per-app tier mapping) | **DISAPPEARS as a central list** — each consumer plugin's `authentik.tier:` field is the source of truth |
| `authentik_domain` etc. core defaults | **STAYS** (referenced by infra-level wiring like Traefik file-provider) |

### 4. Cross-role consumers — `roles/pazny.traefik/` etc.

| Surface | Verdict |
|---|---|
| `roles/pazny.traefik/templates/dynamic/middlewares.yml.j2` — `authentik@file` middleware definition | **STAYS** in traefik role (it's how the traefik file-provider speaks to authentik; install-internal-traefik) |
| `roles/pazny.traefik/templates/dynamic/services.yml.j2` — references `authentik_domain` for the auth.<tld> router | **STAYS** in traefik role (Traefik routes Authentik like any other Tier-1) |

### 5. State catalog — `state/manifest.yml`

Authentik's row stays at top-level (platform service catalog). Adds
`oidc: source` field (vs. Grafana's `oidc: native` consumer field) so
loader knows which plugins are sources vs. consumers.

---

## Source-Specific findings (SR-N)

### SR-1: The aggregator pattern

Today's `authentik_oidc_apps` list is the **only** place a new service's
OIDC config is registered. After thinning, no such central list exists —
each consumer plugin owns its `authentik:` block.

**This requires plugin loader hook 1 (`pre_render`) to AGGREGATE** every
loaded consumer plugin's `authentik:` block, emit a merged blueprint stream,
and hand it to the `authentik-base` plugin's blueprint apply step.

**Loader pseudocode:**

```python
def hook_pre_render():
    consumers = [p for p in loaded_plugins if p.has_block("authentik")]
    aggregated = [p.get("authentik") for p in consumers]
    authentik_base = find_plugin("authentik-base")
    authentik_base.blueprint_inputs["consumers"] = aggregated
    # Now authentik-base's pre_compose hook renders its blueprint templates
    # using the aggregated list, replacing the old `authentik_oidc_apps` var.
```

**This is the single most important loader-architecture finding from V4.**
It generalizes:

- `mailpit-relay` plugin aggregates every consumer plugin's
  `requires.notifier: mail` declarations into a relay-receiver list.
- `prometheus-base` plugin aggregates every consumer plugin's
  `observability.scrape:` blocks into a merged `scrape-config.yml`.
- `traefik-base` plugin (post-Q2) aggregates router declarations.

**Naming:** call this **the aggregator pattern**. Source plugins (those
that are wired-INTO by many consumers) get an `aggregates:` declaration in
their manifest pointing at which consumer-plugin block to harvest. The
loader handles the rest.

### SR-2: Per-agent identity (Track B integration)

Today's `roles/pazny.authentik/templates/blueprints/30-agent-clients.yaml.j2`
defines OAuth clients for `nos-conductor`, `nos-inspektor`, `nos-librarian`,
`nos-scout`, etc. After thinning, **each agent profile under
`files/anatomy/agents/<n>/profile.yml` carries its own `authentik:` block**
(symmetric to consumer plugins). The `authentik-base` plugin aggregates
agent-side declarations the same way it aggregates plugin-side ones.

**This unifies:** consumer plugins + agent profiles + per-plugin clients
all flow through the same aggregator into the same blueprint output.
**One mechanism, three sources** — much cleaner than the three-way
ad-hoc-glue we have today.

### SR-3: Service-side OIDC setup is post-compose work

`tasks/stacks/authentik_service_post.yml` (184 lines!) does work that
**can't happen until both Authentik AND the consumer service are up** —
it tells the consumer "here's your OIDC config" via the consumer's API.
This is plugin loader hook 3 (`post_compose`) territory **for each
consumer plugin individually**, not for `authentik-base`.

After thinning, those 184 lines split across consumer plugins:
- `nextcloud-base/lifecycle/post_compose:` — `occ user:setting` calls
- `gitea-base/lifecycle/post_compose:` — admin API call
- `portainer-base/lifecycle/post_compose:` — `PUT /api/settings`

`authentik-base` itself is done after blueprint apply + readiness probe.
**The biggest cross-cutting file in the repo dissolves into single-line
post-hooks per consumer.**

### SR-4: Authentik must be FIRST in compose-up ordering

Today's `tasks/stacks/core-up.yml` carefully orders: MariaDB+PostgreSQL →
Authentik → other infra → other stacks. The plugin loader's hook-3
(`post_compose`) for ALL consumer plugins must wait for Authentik's
hook-3 to complete (because they call back into Authentik's API to verify
their OIDC client exists).

**Resolution:** plugin loader maintains a dependency graph. Consumers
declaring `requires.plugin: authentik-base` block on its post_compose
completion. Loader processes plugins in topological order per hook.

This is **standard build-system shape** and not a doctrinal challenge —
just an A6 implementation point.

### SR-5: RBAC tier list is now plugin-discovered

`authentik_app_tiers` today maps each Tier-1 service to one of 4 access
groups (`nos-admins` / `nos-managers` / `nos-users` / `nos-guests`). After
thinning, each consumer plugin's `authentik.tier:` is authoritative. The
aggregator (`authentik-base`) renders the `20-rbac-policies.yaml.j2`
blueprint by grouping aggregated consumers by tier.

**Side benefit:** no more "operator forgot to add new service to
`authentik_app_tiers`" silent-no-RBAC class of bugs. Tier is a required
field in plugin schema; loader rejects manifests missing it.

---

## New edge cases vs. Grafana V3

### EC9: Source plugin (vs. consumer plugin) shape

Authentik plugin needs an `aggregates:` block describing what it harvests
from consumer/agent manifests. Schema must support this. **Action:** extend
plugin.schema.json to include `aggregates:` (optional; only source plugins
declare it).

### EC10: Plugin dependency graph + topological ordering

Per-hook ordering is no longer "loop over plugins in any order" — must be
topological per `requires.plugin:` edges. Loader needs a DAG-resolution
step at the start of each hook. **Action:** A6 spec adds DAG step before
each hook fires.

### EC11: Migration recipe for `authentik_oidc_apps` removal

This is the highest-blast-radius change in the repo. Operators with custom
config.yml entries in `authentik_oidc_apps` need a migration path:

1. Migration recipe `migrations/2026-XX-authentik-oidc-apps-decompose.yml`
2. For each entry in operator's old `authentik_oidc_apps`, generate a
   stub `files/anatomy/plugins/<slug>-oidc-only/plugin.yml` shim plugin.
3. Operator reviews stubs, merges with their proper service plugin (most
   will already exist after Q-batches), deletes shim.
4. Once all stubs merged/deleted, drops `authentik_oidc_apps` from config.

**This is post-Q2 cleanup work.** During Q2, the var stays as a
backwards-compat input to the aggregator (loader merges old list + new
plugin blocks).

### EC12: `authentik-migrate.yml` doesn't fit anywhere clean

Today's 123-line legacy-Authentik-instance migration doesn't belong in a
plugin (it runs once per host, never again). Stays as a top-level migration
recipe. **Action:** ensure plugin loader doesn't accidentally trigger it
during normal hooks. Out-of-scope for plugin lifecycle.

### EC13: Embedded outpost auto-binding

Today's `authentik_oidc_setup.yml` auto-binds the embedded outpost to
proxy providers. Same mechanism as service-side OIDC — moves to per-consumer
plugin `lifecycle.post_compose:` for proxy-auth services (Uptime Kuma,
Calibre-Web, etc.). Each consumer's plugin declares `authentik.provider_type:
proxy` (or `oauth2` / `forward_auth`) and the outpost binding is contingent
on that field.

---

## What this inventory tells us about the doctrine (delta vs. Grafana V3)

1. **Source plugins exist as a class of their own** — they don't just install
   + wire, they aggregate from many other plugins. Plugin schema needs to
   reflect this (EC9). **Doctrine refinement: source / consumer / aggregator
   are the three plugin behaviors, NOT just service / skill / composition
   types.** A plugin can be a service AND an aggregator (authentik-base is
   both). A skill plugin can never be a source/aggregator. A composition
   plugin always ties two services but is never a source.

2. **Aggregator pattern is generally applicable.** It's THE answer for
   prometheus scrape merging, mailpit relay routing, traefik router
   declarations, and per-tier RBAC. **All "central registry" lists in
   `default.config.yml` collapse into per-consumer-plugin blocks +
   loader-side aggregation by source plugins.** Net effect: `default.config.yml`
   becomes ~50% shorter post-Q.

3. **Plugin loader needs DAG resolution per hook (EC10).** Topological
   ordering is no longer optional — Authentik must be ready before any
   consumer's post_compose runs. A6 implementation point.

4. **Q2 IAM batch is the highest-blast-radius batch.** Recommended order:
   - Q2.1: introduce `authentik-base` plugin shell + aggregator (no
     consumer migration yet)
   - Q2.2: migrate ONE consumer (recommend `grafana-base` since it's
     already drafted from A6.5)
   - Q2.3: blank → verify
   - Q2.4: migrate remaining consumers in groups (proxy-auth services
     together because they share outpost binding logic; native-OIDC
     services together; …)
   - Q2.5: delete `authentik_oidc_apps` from `default.config.yml` (EC11)

5. **The disappearance of `authentik_oidc_apps`** is the single most
   visible "doctrine works" moment in the entire refactor. Operator's
   "add a service" workflow goes from "edit central list + edit role
   compose template + edit role tasks/post.yml" to "drop a plugin manifest
   in `files/anatomy/plugins/<n>/` and run one tag." That's the §1.1
   promise made literal.

---

## Forward references

- Grafana V3 inventory: `files/anatomy/docs/grafana-wiring-inventory.md`
- 6-step recipe: `files/anatomy/docs/role-thinning-recipe.md`
- Plugin loader spec: `files/anatomy/docs/plugin-loader-spec.md`
- Doctrine source: `docs/bones-and-wings-refactor.md` §1.1
- Refactor PoC plan: `docs/bones-and-wings-refactor.md` §8 (A6.5 = Grafana pilot;
  A6 lifecycle hooks revised post-V3+V4 to 4-hook with DAG resolution)
- Track Q post-PoC plan: `docs/bones-and-wings-refactor.md` §13.1 (Q2 = IAM batch)

## Recipe deltas to land in `role-thinning-recipe.md` v0.2

After this V4 inventory, the recipe needs:

- **Step 1.5: classify the role as source / consumer / aggregator** — drives
  whether step 2 manifest gets an `aggregates:` block.
- **Step 5b: smoke-test against an existing consumer** — for source roles,
  pre-flight requires at least one already-thinned consumer to verify the
  aggregator still works.
- **Pitfall P6: aggregator order matters** — source plugins must be
  manifest-validated BEFORE any consumer is thinned, else loader's hook 1
  has nothing to aggregate against and consumer's `authentik:` block
  becomes orphaned config.

These will be folded into v0.2 of the recipe doc on next pass.
