# Alloy — Skills

> **Alloy has no external skill surface.** It is a telemetry collector (a shipper), not a queryable store and not an actionable service. This file states that plainly so no agent is sent to an invented endpoint.

## Why there are no skills

- **It is a pipe, not a store.** Alloy scrapes metrics, tails logs, and receives OTLP, then forwards them to Prometheus, Loki and Tempo. The *query* surface lives on those backends — see `../prometheus/SKILLS.md`, `../loki/SKILLS.md`, `../tempo/SKILLS.md`, or Grafana for a dashboarded view.
- **Its config is Ansible-owned.** The pipeline is defined in `files/observability/alloy/config.alloy.j2` and rendered by `tasks/observability.yml` to `{{ homebrew_prefix }}/etc/grafana-alloy/config.alloy` (default `/opt/homebrew/etc/grafana-alloy/config.alloy`), which is the only render wired to the reload handler. (`~/.config/alloy/config.alloy` is a second, minimal copy written by the `alloy-base` plugin; the `conf.d/*.river` fragments beside it are dormant. Neither is the running pipeline.) There is no operator- or agent-facing mutation API to reconfigure it at runtime.
- **No auth, no SSO, loopback-only.** The UI on `:12345` and the OTLP receivers (`:4317`/`:4318`, bound to `127.0.0.1`) are host-local; there is no bot account or token to act as.

## The only HTTP surface (inspection, not action)

These are health/inspection endpoints, not invocable skills — an agent reads them, it does not act through them:

- `GET http://localhost:12345/-/ready` → `200 OK` when Alloy is ready.
- `GET http://localhost:12345/metrics` → Alloy's own Prometheus-format self-metrics.
- `http://localhost:12345/` → read-only pipeline inspection UI.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:12345/-/ready
```

To change what Alloy collects, edit the `alloy_scrape_*` / `alloy_tail_*` toggles (or the composition plugins `alloy-host-metrics` / `alloy-docker-metrics` / `alloy-syslog`) and re-run the playbook — that is a playbook action, not a service skill.
