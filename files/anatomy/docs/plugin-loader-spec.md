# Plugin loader specification — A6 implementation contract

> **Status:** v0.1 (2026-05-03), distilled from V3 (Grafana) + V4 (Authentik)
> wiring inventories. **This is the contract A6 implementation must satisfy.**
> The §6.4 narrative in the refactor doc is the operator-facing summary;
> this file is the implementation-facing spec.
>
> Pinned-to-this-version-of-doctrine. Breaking changes require RFC commit.

## Inputs

- All `files/anatomy/plugins/*/plugin.yml` manifests.
- Manifest schema at `state/schema/plugin.schema.json`.
- Ansible variable scope at the moment the loader runs (whatever the
  containing role/task has access to — per-host vars, group vars,
  config.yml, credentials.yml).
- Existing playbook orchestration: `tasks/stacks/core-up.yml`,
  `tasks/stacks/stack-up.yml`, `tasks/stacks/apps-up.yml`.

## Outputs

- Compose-extension fragments in `{{ stacks_dir }}/<stack>/overrides/<plugin>.yml`
- Provisioning files in their target paths (per manifest)
- Authentik blueprint stream merged with consumer + agent inputs
- Wing config registrations in `~/wing/app/config/plugins.neon`
- API-side state in Wing (pulse_jobs, gdpr_processors, audit_log)
- Grafana dashboard registrations (folder-isolated under `Plugins/<plugin>/`)
- Notification template files in `~/anatomy/notifications/templates/`
- Lifecycle events to `~/.nos/events/playbook.jsonl` per existing telemetry contract

## Architecture

```
                             pazny.anatomy --tags anatomy.plugins
                                       │
                                       ▼
                          ┌────────────────────────┐
                          │  load_plugins.py       │  (Python module under
                          │                        │   files/anatomy/scripts/)
                          │  ┌──────────────────┐  │
                          │  │ Discover  │─────►│──┼──► registers each plugin
                          │  │ Validate  │      │  │      in in-memory graph
                          │  │ DAG-build │      │  │
                          │  └──────────────────┘  │
                          │                        │
                          │  ┌──────────────────┐  │
                          │  │ Hook 1           │  │
                          │  │ pre_render       │──┼──► installs requirements,
                          │  │   (topo order)   │  │      aggregates blueprints,
                          │  └──────────────────┘  │      registers Authentik
                          │                        │
                          │  ┌──────────────────┐  │
                          │  │ Hook 2           │  │
                          │  │ pre_compose      │──┼──► renders compose-extension
                          │  │   (topo order)   │  │      fragments + provisioning
                          │  └──────────────────┘  │
                          │                        │
                          │  ┌──────────────────┐  │
                          │  │ Hook 3           │  │
                          │  │ post_compose     │──┼──► API registrations
                          │  │   (topo order)   │  │      (Wing, Pulse, Grafana)
                          │  └──────────────────┘  │
                          │                        │
                          │  ┌──────────────────┐  │
                          │  │ Hook 4           │  │
                          │  │ post_blank       │──┼──► plugin filesystem cleanup
                          │  │   (rev topo)     │  │      (audit rows preserved)
                          │  └──────────────────┘  │
                          └────────────────────────┘
```

## The 4 lifecycle hooks (canonical)

### Hook 1 — `pre_render`

**When:** after vars are loaded, before any role render block in `core-up.yml`/`stack-up.yml`.

**Per plugin (in topological order by `requires.plugin:` edges, sources first):**

1. Discover manifest, validate against schema.
2. Resolve `requires.role` / `requires.feature_flag` / `requires.apps_manifest`.
   Skip plugin if requirement not met.
3. Install host-side requirements (brew/docker/url).
4. **Aggregator step (NEW from V4 — EC9):** if plugin has `aggregates:`
   declaration, walk all loaded plugins (and agent profiles) and harvest
   the named blocks. Store harvested list on plugin's `inputs.<key>`.
5. Register Authentik blueprint inputs (sources only) — emits to the same
   blueprint stream that existing `tasks/stacks/core-up.yml` Authentik
   reconverge consumes. **MUST happen before reconverge.**

**Failure mode:** any plugin's hook-1 failure aborts the entire plugin
loader run. No partial state left behind (nothing has been written to
filesystem yet).

### Hook 2 — `pre_compose`

**When:** after role render block, before `docker compose up <stack> --wait` in
each stack's orchestrator.

**Per plugin (topological order):**

6. Ensure plugin-owned dirs exist.
7. Render compose-extension fragment from manifest's
   `compose_extension.template` → `{{ stacks_dir }}/<stack>/overrides/<plugin>.yml`.
   Existing override-discovery loop in core-up/stack-up picks it up — **no
   orchestrator change needed** (verified during V3 inventory).
8. Render provisioning files (datasources, dashboards, scrape configs)
   into target paths (per manifest's `provisioning:` block).
9. Apply schema migrations (idempotent CREATE TABLE IF NOT EXISTS) against
   wing.db.

**Failure mode:** a plugin's hook-2 failure marks plugin as `degraded`
in pulse state but compose-up still proceeds for OTHER plugins' work.
Failed plugin's stale fragment from a prior run is cleaned up before
write attempt (idempotency).

### Hook 3 — `post_compose`

**When:** after `docker compose up <stack> --wait` for the plugin's
`requires.role`'s stack.

**Per plugin (topological order):**

10. Wait for plugin's target service health (per manifest's `lifecycle.post_compose.wait_health`,
    default = role's primary `health_check.url_template` from `state/manifest.yml`).
11. API-side registrations (each is idempotent UPSERT):
    - Wing routes: write/merge into `~/wing/app/config/plugins.neon`.
    - Pulse jobs: `POST /api/v1/pulse_jobs` with idempotency key
      `<plugin_name>:<job_name>`.
    - Grafana dashboards: `POST /api/dashboards/db` with `overwrite: true`
      and folderUid scoped to plugin (`Plugins/<plugin_name>/`).
    - ntfy/mail templates: write file to `~/anatomy/notifications/templates/<plugin>/<n>`.
12. GDPR row UPSERT: `POST /api/v1/gdpr/processors` with idempotency key
    on plugin name.
13. Wing graceful reload (`brew services restart php@8.3`) IF any plugin
    in this hook batch wrote to `plugins.neon`.
14. Pulse launchd reload IF any plugin in this hook batch registered a job.

**Failure mode:** per-plugin failure marked `degraded`, others continue.
Wing/Pulse reload happens at most once per loader run regardless of how
many plugins triggered it (debounced).

### Hook 4 — `post_blank`

**When:** during `blank=true` runs, BEFORE the `tasks/blank-reset.yml` data
dir wipe.

**Per plugin (REVERSE topological order — consumers cleaned before sources):**

15. Run plugin-declared `lifecycle.post_blank:` actions (remove
    plugin-owned dirs in `~/observability/grafana/provisioning/`, cached
    downloads, etc.).
16. **Audit log preserved.** No plugin can clear `actor_id`-tagged rows
    in wing.db. Plugin schema's `gdpr.retention_days` drives the standard
    retention sweep (separate cron, not this hook).

**Failure mode:** logged, doesn't block the rest of blank-reset (operator
needs blank to complete to recover).

## DAG resolution (topological ordering — EC10)

Loader maintains:
- `nodes`: every loaded plugin.
- `edges`: `(consumer, source)` for every `requires.plugin` declaration.
- Implicit edge: every consumer plugin → `authentik-base` (because OIDC
  consumers can't post_compose until OIDC source is ready).
- Implicit edge: every plugin with `observability.scrape:` →
  `prometheus-base` (post-Q1).

Each hook fires in topo order (sources first). Hook 4 fires in reverse
topo. Cycles abort the loader with a specific error (rare; design intent
is acyclic).

## Aggregator pattern (V4 — SR-1, EC9)

Source plugins declare:

```yaml
aggregates:
  - from: consumer_block
    block_path: authentik       # plugins[*].authentik
    output_var: aggregated_authentik_apps
  - from: agent_profile
    block_path: authentik
    output_var: aggregated_agent_clients
```

Loader at hook 1 step 4 walks all loaded plugins (and agent profiles)
matching the `from` selector, harvests the block_path block, stores under
`inputs.<output_var>` on the source plugin's namespace.

Source plugin's compose-extension / provisioning / blueprint templates
then reference `{{ inputs.aggregated_authentik_apps }}` (Jinja).

This is the mechanism by which `authentik_oidc_apps` (today's central
list) **disappears** post-Q2: each consumer plugin owns its block; loader
re-aggregates per run.

## Manifest schema requirements (extension over §6.3 PoC shape)

All from V3+V4 findings. Field-level:

| Field | Type | Required? | Source |
|---|---|---|---|
| `name` | str | yes | §6.3 PoC |
| `version` | semver str | yes | §6.3 PoC |
| `type` | list[skill\|service\|composition] | yes | §6.3 PoC |
| `requires` | object | yes (may be empty) | §6.3 PoC |
| `requires.role` | str (role name) | service-only | V3 |
| `requires.apps_manifest` | str (path) | composition-Tier-2 | §6.2 |
| `requires.plugin` | list[plugin name] | optional, drives DAG | V4 EC10 |
| `requires.feature_flag` | str (var name) | optional | V3 |
| `requires.variables` | list[str] | optional | V3 P1 |
| `aggregates` | list[obj] | source-plugins-only | V4 SR-1 |
| `lifecycle.pre_render` | list[action] | optional | NEW spec |
| `lifecycle.pre_compose` | list[action] | optional | V3 EC5 |
| `lifecycle.post_compose` | list[action] | optional | V3 EC5 |
| `lifecycle.post_blank` | list[action] | optional | V3 EC5 |
| `compose_extension` | object | optional, service-class | V3 EC1 |
| `compose_extension.template` | str (path) | required-if-block-present | V3 |
| `compose_extension.target_stack` | str | required-if-block-present | V3 |
| `compose_extension.target_service` | str | required-if-block-present | V3 P2 |
| `provisioning` | object | optional | V3 |
| `authentik` | object | optional, declares OIDC client | V3+V4 |
| `authentik.client_id` | str | required-if-block-present | V3 |
| `authentik.client_secret` | str (Jinja) | required-if-block-present | V3 |
| `authentik.tier` | int 1-4 | required-if-block-present | V4 SR-5 |
| `authentik.provider_type` | enum oauth2\|proxy\|forward_auth | optional | V4 EC13 |
| `authentik.scopes` | list[str] | optional | V3 |
| `gdpr` | object | required (parser refuses without) | doctrine |
| `observability` | object | optional | V3 |
| `observability.metrics` | list[obj] | optional | V3 |
| `observability.scrape` | object | optional, harvested by prometheus-base | V4 future |
| `ui-extension` | object | optional | §6.3 PoC |
| `notification` | object | optional | §6.3 PoC |
| `schema` | list[path] | optional | §6.3 PoC |

## Critical ordering invariants (all must hold)

| Invariant | From |
|---|---|
| Hook 1 step 5 → before existing Authentik blueprint reconverge | V3 P4 |
| Hook 2 → before `docker compose up <stack>` | V3 EC5 |
| Hook 3 → after `docker compose up <stack> --wait` | V3 EC5 |
| Hook 4 → before `tasks/blank-reset.yml` data dir wipe | V3 EC5 |
| Each hook → topological per plugin DAG (sources first; hook 4 reversed) | V4 EC10 |
| `authentik-base` plugin must be loadable BEFORE any consumer plugin is migrated | V4 P6 |
| Compose-extension `target_service` MUST match role compose's `services.<name>` | V3 P2 |

## Implementation skeleton (Python)

```python
# files/anatomy/module_utils/load_plugins.py
class PluginLoader:
    def __init__(self, manifest_glob: str, vars: dict):
        self.plugins = []  # discovered + validated
        self.dag = nx.DiGraph()
        self.vars = vars

    def discover(self): ...
    def validate(self, plugin: Plugin): ...
    def build_dag(self): ...
    def topo_order(self, reverse=False): ...

    def hook_pre_render(self): ...
    def hook_pre_compose(self): ...
    def hook_post_compose(self): ...
    def hook_post_blank(self): ...

    def run(self, hook: str):
        # Called from Ansible at the canonical hook points.
        # Hooks 1+2+3 run in normal order; hook 4 in reverse.
        ...
```

Wired from Ansible via `ansible.builtin.command` task (or a custom module
under `files/anatomy/library/nos_plugin_loader.py` if we want structured
output — recommended).

## Tests A6 must include

| Test | Why |
|---|---|
| Manifest schema validates 3 reference plugins (gitleaks, grafana-base, authentik-base) | Schema completeness |
| DAG-build rejects cyclic graphs | Sanity |
| Aggregator harvests correctly with 5 mock consumers | V4 SR-1 |
| Hook 1 idempotency — second run is no-op | Re-converge correctness |
| Hook 2 compose-fragment merges with role's fragment via Docker Compose `-f` | V3 EC1 + P2 |
| Hook 3 dashboard POST is folder-scoped | `Plugins/<n>/` prefix |
| Hook 4 reverse-topo ordering (mock 3-plugin DAG, observe order) | V4 EC10 |
| Authentik blueprint apply succeeds with aggregator output | V4 SR-1 |
| Plugin failure in hook 2 doesn't block other plugins (degradation, not abort) | Hook 2 spec |
| Plugin removal (`-e remove_plugin=foo`) reverses all hooks | §6.5 |

Target: ~30 tests under `tests/anatomy/test_plugin_loader.py`. Plus
~10 schema tests under `tests/anatomy/test_plugin_schema.py`.

## Out of scope for A6 (deferred)

- **Composition plugin runtime activation logic.** A6 only validates +
  loads composition plugins; activation when both required services
  install is a separate Q-track concern.
- **Plugin hot-reload.** Today plugins reload only on `--tags
  anatomy.plugins` runs. Future: filesystem watch + automatic reload.
- **Multi-tenant plugin namespacing.** All plugins today have global names;
  future may need `<tenant>.<plugin>` namespacing.
- **Plugin signing / supply chain.** Out-of-scope; track separately.

## Open questions (for operator)

- **OQ1:** Should `tasks/authentik-migrate.yml` (123 lines, legacy migration)
  move to `migrations/2026-XX-authentik-instance-port.yml` shape, or stay
  as-is? V4 EC12 flagged but no decision yet.
- **OQ2:** Should hook 3 dashboard registration be incremental (POST per
  dashboard) or batch (one big payload)? Trade-off: rate limit vs. failure
  granularity.
- **OQ3:** Plugin loader as Python script vs. custom Ansible module.
  Module gives structured changed/failed events but adds dev friction.
  Default position: custom module (better Ansible-native experience).

## Versioning

| Version | Date | Change |
|---|---|---|
| v0.1 | 2026-05-03 | Initial spec consolidating V3 (grafana inventory) + V4 (authentik inventory) findings into 4-hook + DAG + aggregator architecture |
