# grafana-prometheus — composition plugin

Wires `grafana-base` and `prometheus-base` together by emitting a Grafana
datasource provisioning fragment that names the Prometheus peer in the
observability stack as a Grafana data source.

## Status

Track Q1b — first composition plugin past the A6.5 doctrine gate. Validates
the "composition plugin" shape (`type: [composition]` + `requires.plugin: [...]`)
described in `docs/bones-and-wings-refactor.md` §1.1 / §6 and the
`plugin-loader-spec.md` §6.2 contract.

## What it does

1. Activates only when **both** `grafana-base` and `prometheus-base` are
   loaded and `install_observability: true`.
2. On `pre_compose`, renders
   `provisioning/datasources/prometheus.yml.j2` into
   `~/observability/grafana/provisioning/datasources/grafana-prometheus.yml`.
3. The file contributes one datasource entry (`Prometheus`, `uid:
   prometheus`, default) to Grafana's provisioning, alongside whatever
   `grafana-base/provisioning/datasources/all.yml` contributes. Grafana 9+
   concatenates the `datasources:` lists across files at boot.

## Why composition (not "just put it in grafana-base")?

Neither `grafana-base` nor `prometheus-base` alone "knows" about the other.
The wiring is structural — it only makes sense when both services are
installed. Composition plugins encode the "two peers, one tendon" pattern
without polluting either base manifest with peer-aware templating.

## File layout

```
files/anatomy/plugins/grafana-prometheus/
├── plugin.yml
├── provisioning/datasources/prometheus.yml.j2
├── manifest.fragment.yml             # intentionally empty
└── README.md
```

## Operator debugging

```bash
ls ~/observability/grafana/provisioning/datasources/
# all.yml                       <- from grafana-base
# grafana-prometheus.yml        <- from this plugin
# (future) grafana-loki.yml     <- from grafana-loki composition
# (future) grafana-tempo.yml    <- from grafana-tempo composition
```

The filename matches the plugin slug, so ownership is obvious at a glance.

## Related

- `files/anatomy/plugins/grafana-base/plugin.yml` — owner of Grafana's
  provisioning index + plugin defaults.
- `files/anatomy/plugins/prometheus-base/plugin.yml` — owner of
  Prometheus's master config + recording rules.
- `files/anatomy/docs/plugin-loader-spec.md` §6.2 — composition plugin
  shape contract.
