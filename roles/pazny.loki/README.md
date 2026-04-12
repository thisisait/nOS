# pazny.loki

Ansible role for deploying **Loki** as a compose override fragment in the devBoxNOS `observability` stack. Co-deployed alongside Grafana / Prometheus / Tempo.

Part of [devBoxNOS](../../README.md) Wave 2.2 observability-peers role extraction (sibling to `pazny.grafana`, `pazny.prometheus`, `pazny.tempo`).

## What it does

Invoked from `tasks/stacks/core-up.yml` **before** `docker compose up observability`:

- Creates `{{ loki_storage_path }}` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/observability/overrides/loki.yml`
- The override is picked up by core-up's `find + -f` loop and merged into the observability compose project
- Notifies `Restart loki` if the override template changed

## Loki config (NOT in the role)

The `local-config.yaml` is still rendered by `tasks/stacks/core-up.yml` from `files/observability/loki/local-config.yaml`. It is deliberately left outside the role because it depends on play-level state (retention overrides, schema config). The compose override mounts the rendered file into the container read-only at `/etc/loki/local-config.yaml`.

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level (`observability_net` + external shared network must exist in the base compose file)
- A top-level `Restart loki` handler in the consuming playbook (role-local fallback also provided)

## Variables

| Variable | Default | Description |
|---|---|---|
| `loki_version` | `latest` | Upstream `grafana/loki` image tag |
| `loki_port` | `3100` | Exposed on `127.0.0.1` only |
| `loki_retention` | `744h` | Log retention window (31 days) |
| `loki_storage_path` | `~/observability/loki` | Host bind mount for chunk + index data |
| `loki_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `loki_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |

## Usage

From `tasks/stacks/core-up.yml`, gated on `install_observability`:

```yaml
- name: "[Core] Render pazny.loki compose override + data dir"
  ansible.builtin.include_role:
    name: pazny.loki
  when: install_observability | default(true)
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `loki:` service block in `templates/stacks/observability/docker-compose.yml.j2`
2. Remove the leftover override file at `~/stacks/observability/overrides/loki.yml`
