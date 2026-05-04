# grafana-loki

**Type:** composition
**Status:** Track Q1b cross-wiring batch (2026-05-04)
**Requires:** `grafana-base` + `loki-base`, `install_observability=true`

## What it does

Wires the `loki-base` service plugin into `grafana-base` by emitting a Grafana
datasource provisioning file (`loki.yml`) into Grafana's
`provisioning/datasources/` directory. This makes Loki appear as a datasource
(uid `loki`) and unlocks:

- LogQL queries from the Grafana Explore tab.
- Tempo `lokiSearch` correlation — clicking a trace span jumps to the matching
  log lines.
- Derived-field link from a Loki log line's `"trace_id":"..."` JSON field back
  into the Tempo trace view.

## Why a separate plugin

Pre-Q1b, the Loki datasource block lived inside grafana-base's
`all.yml.j2`. That tied a Grafana service plugin to Loki specifics — every new
datasource grew the file and added cross-service knowledge to grafana-base. The
composition pattern hosts that wiring in its own plugin, keyed on both
prerequisites being loaded:

```
requires:
  plugin:
    - grafana-base
    - loki-base
```

The plugin loader's DAG ensures both prerequisites resolve before this
composition runs its `pre_compose` hook.

## Files

```
files/anatomy/plugins/grafana-loki/
├── plugin.yml
├── README.md                                       # this file
├── manifest.fragment.yml                           # state/manifest.yml fragment
└── provisioning/
    └── datasources/
        └── loki.yml.j2                             # rendered → ~/observability/grafana/provisioning/datasources/loki.yml
```

## Lifecycle

| Hook | Action |
|------|--------|
| `pre_compose` | `ensure_dir` provisioning path, `render` `loki.yml` |
| `post_blank`  | `remove_file` `loki.yml` |

No compose extension, no Authentik client, no schema. Pure cross-service
provisioning tendon.

## GDPR

Stores nothing. Records `log_query_metadata` as a category for completeness so
the Article 30 register reflects that Grafana can be used to query operator
log data.
