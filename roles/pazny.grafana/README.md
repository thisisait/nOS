# pazny.grafana

Ansible role for deploying **Grafana** as a compose override fragment in the devBoxNOS `observability` stack. Co-deployed alongside Prometheus / Loki / Tempo (which remain in the base compose template pending their own Wave 2.2 role extraction).

Part of [devBoxNOS](../../README.md) Wave 2 role extraction pilot. Third of three base roles (`pazny.glasswing`, `pazny.mariadb`, **`pazny.grafana`**).

## What it does

Two invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up observability`:
   - Creates `{{ grafana_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/observability/overrides/grafana.yml`
   - Notifies `Restart grafana` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose up observability --wait`:
   - Confirms the grafana container is running (via `compose ps -q`)
   - Waits for the `/api/health` endpoint to return 200 (20 × 3s retry)
   - Executes `grafana-cli admin reset-admin-password` to converge the admin password on every run (the `GF_SECURITY_ADMIN_PASSWORD` env var is only read on first DB init, so non-blank runs with rotated `global_password_prefix` need this CLI reconverge path)

## Provisioning files (NOT in the role)

Grafana's datasource + dashboard provisioning renders still live in `tasks/stacks/core-up.yml`:

```
{{ stacks_dir }}/observability/grafana/provisioning/datasources/all.yml
{{ stacks_dir }}/observability/grafana/provisioning/dashboards/all.yml
```

These depend on play-level state (the Authentik OIDC registry, the dynamic service list from `files/health-probes.yml`, dashboard download from the Grafana marketplace) that doesn't cleanly belong in a standalone role. They are deliberately left in `core-up.yml` for the Wave 2.1 pilot; Wave 2.2+ may revisit as the provisioning format matures.

The compose override mounts the directory into the container read-only, so whenever `core-up.yml` renders the provisioning files, the grafana container picks them up via its standard filesystem watch (or a restart notification when the bind source changes).

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level (`observability_net` + external shared network must exist in the base compose file)
- A top-level `Restart grafana` handler in the consuming playbook (role-local fallback also provided)
- (Optional) `install_authentik | default(false)` for the OIDC block; when false the Authentik env vars collapse and Grafana falls back to local auth

## Variables

| Variable | Default | Description |
|---|---|---|
| `grafana_version` | `12.4.2` | Pinned for CVE-2026-27876 (CVSS 9.1 file-write → RCE) |
| `grafana_port` | `3000` | Exposed on `127.0.0.1` unless `services_lan_access: true` |
| `grafana_domain` | `grafana.dev.local` | Used for `GF_SERVER_DOMAIN` and OIDC redirect URIs |
| `grafana_data_dir` | `{{ stacks_dir }}/observability/grafana/data` | Bind mount for SQLite state |
| `grafana_admin_user` | `admin` | Initial admin username |
| `grafana_admin_password` | *(from credentials)* | Rotated through `global_password_prefix` |
| `grafana_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |

## Usage

From `tasks/stacks/core-up.yml`, gated on `install_observability`:

```yaml
# Before observability compose up
- name: "[Core] Render pazny.grafana compose override + data dir"
  ansible.builtin.include_role:
    name: pazny.grafana
  when: install_observability | default(true)

# ... core-up.yml renders provisioning files + runs docker compose up ...

# After observability compose up
- name: "[Core] Grafana admin password reconverge (pazny.grafana → post.yml)"
  ansible.builtin.include_role:
    name: pazny.grafana
    tasks_from: post.yml
  when:
    - install_observability | default(true)
    - _core_observability_enabled | bool
```

## Rollback

Revert the commit that introduced this role and:

1. Restore the `grafana:` service block in `templates/stacks/observability/docker-compose.yml.j2`
2. Restore `tasks/iiab/grafana_admin.yml`
3. Restore the `include_tasks` call in `tasks/stacks/core-up.yml`
4. Delete the leftover override file at `~/stacks/observability/overrides/grafana.yml`
