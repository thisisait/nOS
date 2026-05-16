# pazny.influxdb

Ansible role for deploying **InfluxDB 2.x** as a compose override fragment in the nOS `observability` stack. Co-deployed alongside Grafana / Prometheus / Loki / Tempo.

## What it does

Invoked from `tasks/stacks/core-up.yml` **before** `docker compose up observability`:

- Creates `{{ influxdb_data_dir }}` and `{{ influxdb_config_dir }}` on the host
- Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/observability/overrides/influxdb.yml`
- The override is picked up by core-up's `find + -f` loop and merged into the observability compose project
- On first run, InfluxDB container auto-provisions admin user, initial org (`nos`), bucket (`default`), and admin token using `DOCKER_INFLUXDB_INIT_*` env vars
- Notifies `Restart influxdb` if the override template changed

## SSO

InfluxDB OSS 2.x does not support native OIDC — UI access is gated by **Authentik forward_auth** in the nginx vhost (proxy-auth pattern, same as Uptime Kuma / Calibre-Web). API clients continue to authenticate with the native InfluxDB token (auto-generated at first run, stored in `influxdb_admin_token`).

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at play level (`observability_net` + external shared network in base compose file)
- `influxdb_admin_password` + `influxdb_admin_token` set in `default.credentials.yml` / main.yml auto-gen block

## Variables

| Variable | Default | Description |
|---|---|---|
| `influxdb_version` | `2.7.12` | Upstream `influxdb` image tag (2.x stable only — 3.x is alpha) |
| `influxdb_port` | `8086` | Exposed on `127.0.0.1` only |
| `influxdb_domain` | `influx.{{ instance_tld }}` | Vhost domain |
| `influxdb_data_dir` | `~/influxdb/data` | TSM storage bind mount |
| `influxdb_config_dir` | `~/influxdb/config` | Config bind mount |
| `influxdb_init_username` | `admin` | First-run admin user |
| `influxdb_init_org` | `nos` | First-run initial org |
| `influxdb_init_bucket` | `default` | First-run initial bucket |
| `influxdb_init_retention` | `90d` | First-run bucket retention |
| `influxdb_mem_limit` | `1g` | Container mem limit |
| `influxdb_cpus` | `1.0` | Container CPU limit |

## Usage

From `tasks/stacks/core-up.yml`, gated on `install_influxdb`:

```yaml
- name: "[Core] pazny.influxdb render"
  ansible.builtin.include_role:
    name: pazny.influxdb
    apply: { tags: ['influxdb', 'observability'] }
  when: install_influxdb | default(false)
  tags: ['influxdb', 'observability']
```

Auto-wired via `files/anatomy/plugins/influxdb-base/plugin.yml`. Flip `install_influxdb: true` and re-run the playbook.

## Future work

- **Grafana datasource auto-provisioning** for InfluxDB is NOT part of this role. A follow-up PR can add an InfluxDB datasource entry to `files/observability/grafana/provisioning/datasources/all.yml.j2` (or a post-start task in `pazny.grafana`) using `{{ influxdb_admin_token }}` and `http://influxdb:8086` (shared network DNS).

## Rollback

Revert the commit that introduced this role and remove the leftover override at `~/stacks/observability/overrides/influxdb.yml`.
