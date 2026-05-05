# grafana-tempo

> **Status:** scaffolded 2026-05-04 (Phase 1 U4). Composition plugin.

Cross-wires `grafana-base` (datasource consumer) with `tempo-base` (the trace
backend). Provisions a Grafana Tempo datasource, with service-map
(Prometheus) + trace-to-logs (Loki) deep-linking enabled.

This plugin owns no Tier-1 service of its own — it is pure wiring. Validates
plugin shape #7 (composition) per `docs/bones-and-wings-refactor.md` §6.

## What lives here

```
files/anatomy/plugins/grafana-tempo/
├── plugin.yml                                # manifest
├── manifest.fragment.yml                     # Phase 2 C2 merge target (note)
├── README.md                                 # this file
└── provisioning/
    └── datasources/
        └── tempo.yml.j2                      # Grafana datasource fragment
```

## DAG

The loader resolves `requires.plugin` before this plugin's `pre_compose`
hook fires:

1. `grafana-base` (provisioning dirs ready, Grafana service up)
2. `tempo-base` (Tempo service up, OTLP receivers live)
3. `grafana-tempo` (renders the Tempo datasource fragment into the
   shared provisioning dir)

## Required operator vars

| Var | Default | Source |
|---|---|---|
| `tempo_http_port` | `3200` | `roles/pazny.tempo/defaults/main.yml` |
| `install_observability` | `true` | `default.config.yml` |

The datasource Jinja references no other vars beyond the service-name
hostname (`tempo`) which is resolved by Docker DNS inside the
`observability` compose project.

## E2E recipe

```bash
# Bring up grafana + tempo
ansible-playbook main.yml --tags "stacks,observability" -K

# Verify Grafana sees the datasource
curl -s -u admin:$(rg grafana_admin_password credentials.yml | awk '{print $2}') \
    http://127.0.0.1:3000/api/datasources/name/Tempo | jq '.type, .url'

# Health probe
curl -s -u admin:... http://127.0.0.1:3000/api/datasources/uid/tempo/health \
    | jq '.status'    # expect: "OK"
```

A synthetic span search via `/api/datasources/proxy/uid/tempo/api/search`
should return rows once any traced service has emitted spans.

## GDPR

| Field | Value |
|---|---|
| Data categories | `trace_spans`, `request_metadata` |
| Data subjects | `operators` (Grafana access is admin-only via SSO) |
| Legal basis | `legitimate_interests` |
| Retention | 14 days (aligned with Tempo's local-block retention) |
| Processors | `grafana`, `tempo` |
| EU residency | true (local storage) |

This plugin introduces NO net-new data — it only exposes Tempo's spans
inside Grafana's UI. The retention horizon mirrors `tempo-base` because
that's the only place spans actually live.

## Pre-Q1b note

Today, `grafana-base` ships a combined `provisioning/datasources/all.yml.j2`
that already declares Prometheus + Loki + Tempo + (optional) Wing SQLite +
(optional) InfluxDB sources in one file. Once Q1b lands and `grafana-base`
sheds its non-built-in datasources, this composition plugin becomes the
sole owner of Tempo provisioning. Until then, Grafana auto-merges multiple
datasource files in `provisioning/datasources/` — having both `all.yml`
(from grafana-base) and `tempo.yml` (from this plugin) is harmless: same
`uid: tempo`, same URL.
