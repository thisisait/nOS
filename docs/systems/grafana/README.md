# Grafana

> Vizualizace metrik, logu a traces. Centralalni observability dashboard.

## Quick Reference

| | |
|---|---|
| **URL** | `https://grafana.dev.local` |
| **Port** | `3000` |
| **Stack** | `observability` |
| **Toggle** | `install_observability: true` |
| **Compose** | `~/stacks/observability/docker-compose.yml` |
| **Data** | `~/stacks/observability/grafana/data` |

## Authentication

- **Admin user:** `admin`
- **Admin password:** `{global_password_prefix}_pw_grafana`
- **SSO:** Authentik OIDC (`grafana`)

## API Access

- **Base URL:** `https://grafana.dev.local/api/`
- **Auth method:** Bearer token (Service Account)
- **Bot account:** `openclaw-bot` (auto-created by playbook)
- **Token location:** `~/agents/tokens/grafana.token`

## Health Check

- **Endpoint:** `GET /api/health`
- **Expected:** `200 OK` with `{"commit":"...","database":"ok","version":"..."}`

## Data Sources

| Name | Type | Purpose |
|------|------|---------|
| Prometheus | metrics | System + service metrics via Alloy |
| Loki | logs | Nginx, PHP-FPM, agent logs via Alloy |
| Tempo | traces | OTLP traces (gRPC :4317, HTTP :4318) |

## Dependencies

- Prometheus (metrics backend)
- Loki (log backend)
- Tempo (trace backend)
- Authentik (SSO, optional)
