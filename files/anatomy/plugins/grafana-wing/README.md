# grafana-wing — composition plugin

Registers **Wing's SQLite store** as a Grafana datasource so the SQLite-backed
dashboards have something to query.

## What it wires

```
wing.db  ──(bind-mount, ro)──►  /var/lib/grafana/wing/wing.db
                                        ▲
   grafana-wing renders ───────────────┘
   provisioning/datasources/wing.yml  (uid: wing_sqlite,
                                        type: frser-sqlite-datasource)
```

The Grafana container already mounts Wing's data dir read-only (see
`roles/pazny.grafana/templates/compose.yml.j2`, gated on `install_wing`), and
the `frser-sqlite-datasource` plugin is installed via `GF_INSTALL_PLUGINS`
(`files/anatomy/plugins/grafana-base/templates/grafana-base.compose.yml.j2`).
The only missing link was the **datasource registration** — this plugin
supplies it.

## Why a separate composition plugin

The P1 refactor (2026-05-05) split the Prometheus / Loki / Tempo datasources
out of the monolithic `grafana-base/provisioning/datasources/all.yml.j2` into
sibling composition plugins to fix a duplicate-uid / duplicate-default crash.
The Wing SQLite datasource was left behind in the now-orphaned `all.yml.j2`,
which no plugin renders — so `uid: wing_sqlite` was never provisioned and every
panel keyed to it (all of `99-playbook`, the Ansible-task-rate panel in
`22-ai-agents`) rendered empty against a fully-populated `wing.db`.
`grafana-wing` is the missing sibling.

## Activation

Activates only when **both** `grafana-base` (`install_observability`) **and**
`wing-base` (`install_wing`) are loaded. `requires.plugin` is an activation
gate, so on a Wing-less host the datasource is simply never written — no broken
"missing wing.db" datasource.

## Verify

```bash
ls ~/stacks/observability/grafana/provisioning/datasources/   # → wing.yml present
curl -s http://127.0.0.1:3000/api/datasources | jq '.[].uid'  # → includes "wing_sqlite"
```

Then the `99-playbook` dashboard panels populate immediately (the data was
already in `wing.db`).
