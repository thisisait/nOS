# Grafana

> Visualization of metrics, logs and traces. The estate's central observability dashboard.

## Quick Reference

| | |
|---|---|
| **URL** | `https://grafana.dev.local` |
| **Port** | `3000` |
| **Stack** | `observability` |
| **Toggle** | `install_observability: true` |
| **Image** | `grafana/grafana:12.4.4` (`grafana_version`) |
| **Compose** | `~/stacks/observability/docker-compose.yml` |
| **Data** | `{{ grafana_data_dir }}` = `{{ nos_data_root }}/platform/services/grafana/data` → default `~/nos/platform/services/grafana/data` |
| **Container mount** | host data → `/var/lib/grafana` |

Data-path note: `nos_data_root` defaults to `~/nos`. On external storage the path is
overridden to `{{ external_storage_root }}/observability/grafana`
(`tasks/stacks/external-paths.yml`). The two other mounts Grafana gets are **config, not
data** and stay where they are: `~/stacks/observability/grafana/provisioning` (rendered
datasource + dashboard providers) and `~/observability/dashboards` (dashboard JSONs,
read-only). With `install_wing` on, Wing's `wing.db` is additionally bind-mounted
read-only at `/var/lib/grafana/wing` — that is Wing's data, not Grafana's.

> **Source disagreement (unresolved, flagged not fixed):** `state/manifest.yml` records
> `image: grafana/grafana-oss` while `roles/pazny.grafana/templates/compose.yml.j2`
> actually pulls `grafana/grafana`. The compose template is what runs; the manifest row
> feeds the version/upgrade advisor. Reconcile in source, not here.

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_grafana`
- **SSO:** Authentik OIDC (`grafana`)

## API Access

- **Base URL:** `https://grafana.dev.local/api/` (loopback: `http://127.0.0.1:3000/api/`)
- **Auth method:** Bearer token (Grafana Service Account), or HTTP basic auth as the
  admin user — the playbook itself uses basic auth over loopback.
- **Service account:** `mcp-gateway`, role **Viewer**, auto-created by
  `roles/pazny.mcp_gateway/tasks/post.yml` (gated on `mcp_enable_grafana`). It is the
  only service account nOS provisions in Grafana.
- **Token location:** `{{ mcpo_data_dir }}/.grafana_sa_token` → default
  `~/nos/platform/services/mcpo/data/.grafana_sa_token` (mode `0600`).

> There is **no `openclaw-bot` account and no `~/agents/tokens/` directory** anywhere in
> this repo — both were doc-only fictions carried by the pre-`nos_data_root` tree.

## Health Check

- **Endpoint:** `GET /api/health`
- **Expected:** `200 OK` with `{"commit":"...","database":"ok","version":"..."}`

## Data Sources

Each datasource is provisioned by its own composition plugin, which renders a fragment
into `~/stacks/observability/grafana/provisioning/datasources/`.

| Name | Type (`uid`) | Purpose | Provisioned by |
|------|------|---------|----------------|
| Prometheus | `prometheus` (`prometheus`) | System + service metrics via Alloy | `grafana-prometheus` |
| Loki | `loki` (`loki`) | Nginx, PHP-FPM, agent logs via Alloy | `grafana-loki` |
| Tempo | `tempo` (`tempo`) | OTLP traces (gRPC :4317, HTTP :4318) | `grafana-tempo` |
| Wing SQLite | `frser-sqlite-datasource` (`wing_sqlite`) | Playbook events, migration / upgrade / coexistence history, agent-session telemetry — direct read-only read of `wing.db` | `grafana-wing` |

## Dependencies

- Prometheus (metrics backend)
- Loki (log backend)
- Tempo (trace backend)
- Authentik (SSO, optional)
- Wing (optional — supplies the `wing_sqlite` datasource and the `frser-sqlite-datasource`
  plugin install, both gated on `install_wing`)
