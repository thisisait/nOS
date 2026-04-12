# pazny.tempo

Ansible role for deploying **Tempo** as a compose override fragment in the devBoxNOS `observability` stack. Co-deployed alongside Grafana / Prometheus / Loki.

Part of [devBoxNOS](../../README.md) Wave 2.2 observability-peers role extraction (sibling to `pazny.grafana`, `pazny.prometheus`, `pazny.loki`).

## What it does

Invoked from `tasks/stacks/core-up.yml` **before** `docker compose up observability`:

- Creates `{{ tempo_storage_path }}` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/observability/overrides/tempo.yml`
- The override is picked up by core-up's `find + -f` loop and merged into the observability compose project
- Notifies `Restart tempo` if the override template changed

## Tempo config (NOT in the role)

The `tempo.yaml` is still rendered by `tasks/stacks/core-up.yml` from `files/observability/tempo/tempo.yaml`. It is deliberately left outside the role because it depends on play-level state (OTLP receiver ports, retention overrides). The compose override mounts the rendered file into the container read-only at `/etc/tempo.yaml`.

## Healthcheck disabled

Tempo runs on a **distroless image** that has no `curl` / `wget`, and the `tempo` CLI has no `-config.verify` flag. The role preserves `healthcheck.disable: true` from the base compose. Readiness is observed via the `/ready` HTTP endpoint on port 3200 (Grafana datasource + Alloy scrape detects failures).

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level (`observability_net` + external shared network must exist in the base compose file)
- A top-level `Restart tempo` handler in the consuming playbook (role-local fallback also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `tempo_version` | `2.10.0` | Upstream `grafana/tempo` image tag |
| `tempo_http_port` | `3200` | HTTP query + `/ready` endpoint |
| `tempo_otlp_grpc_port` | `4327` | Internal OTLP gRPC (Alloy → Tempo) |
| `tempo_otlp_http_port` | `4328` | Internal OTLP HTTP (Alloy → Tempo) |
| `tempo_retention` | `168h` | Trace retention window (7 days) |
| `tempo_storage_path` | `~/observability/tempo` | Host bind mount for trace blocks |
| `tempo_mem_limit` | `{{ docker_mem_limit_light }}` | Defaults to `512m` |
| `tempo_cpus` | `{{ docker_cpus_light }}` | Defaults to `0.5` |

## Usage

From `tasks/stacks/core-up.yml`, gated on `install_observability`:

```yaml
- name: "[Core] Render pazny.tempo compose override + data dir"
  ansible.builtin.include_role:
    name: pazny.tempo
  when: install_observability | default(true)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `tempo:` service block in `templates/stacks/observability/docker-compose.yml.j2`
2. Remove the leftover override file at `~/stacks/observability/overrides/tempo.yml`
