# pazny.prometheus

Ansible role for deploying **Prometheus** as a compose override fragment in the devBoxNOS `observability` stack. Co-deployed alongside Grafana / Loki / Tempo.

Part of [devBoxNOS](../../README.md) Wave 2.2 observability-peers role extraction (sibling to `pazny.grafana`, `pazny.loki`, `pazny.tempo`).

## What it does

Invoked from `tasks/stacks/core-up.yml` **before** `docker compose up observability`:

- Creates `{{ prometheus_storage_path }}` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/observability/overrides/prometheus.yml`
- The override is picked up by core-up's `find + -f` loop and merged into the observability compose project
- Notifies `Restart prometheus` if the override template changed

## Prometheus config (NOT in the role)

The `prometheus.yml` scrape config is still rendered by `tasks/stacks/core-up.yml` from `files/observability/prometheus/prometheus.yml`. It is deliberately left outside the role because it depends on play-level state (Alloy scrape targets, host exporter ports, dashboard download). The compose override mounts the rendered file into the container read-only at `/etc/prometheus/prometheus.yml`.

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level (`observability_net` + external shared network must exist in the base compose file)
- A top-level `Restart prometheus` handler in the consuming playbook (role-local fallback also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `prometheus_version` | `latest` | Upstream `prom/prometheus` image tag |
| `prometheus_port` | `9090` | Exposed on `127.0.0.1` only |
| `prometheus_retention` | `30d` | TSDB retention window |
| `prometheus_storage_path` | `~/observability/prometheus` | Host bind mount for TSDB data |
| `prometheus_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `prometheus_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |

## Usage

From `tasks/stacks/core-up.yml`, gated on `install_observability`:

```yaml
- name: "[Core] Render pazny.prometheus compose override + data dir"
  ansible.builtin.include_role:
    name: pazny.prometheus
  when: install_observability | default(true)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `prometheus:` service block in `templates/stacks/observability/docker-compose.yml.j2`
2. Remove the leftover override file at `~/stacks/observability/overrides/prometheus.yml`
