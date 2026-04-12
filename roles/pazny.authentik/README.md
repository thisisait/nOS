# pazny.authentik

Ansible role for deploying **Authentik** (SSO / Identity Provider) as a compose override fragment in the devBoxNOS `infra` stack. Renders both the `authentik-server` and `authentik-worker` services from a single fragment, plus the declarative blueprint YAML that drives admin user, RBAC groups, OAuth2 / proxy providers, applications, and tier-based policy bindings.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (infra IAM unit).

## What it does

Three invocation modes from `tasks/stacks/core-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
   - Creates `{{ authentik_data_dir }}` on the host
   - Creates `{{ stacks_dir }}/infra/authentik/blueprints` (bind source for `/blueprints/custom:ro`)
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/authentik.yml` (both `authentik-server` + `authentik-worker` in one fragment)
   - Includes `blueprints.yml` which renders the 3 blueprint templates into the shared bind path
   - Notifies `Restart authentik` on compose change, `Reapply authentik blueprints` on any blueprint change

2. **Blueprints (`tasks/blueprints.yml`)** — invoked by `tasks/main.yml`:
   - Renders `00-admin-groups.yaml`, `10-oidc-apps.yaml`, `20-rbac-policies.yaml` into `{{ stacks_dir }}/infra/authentik/blueprints/`
   - Each template change notifies `Reapply authentik blueprints`

3. **Post (`tasks/post.yml`)** — runs *after* `docker compose up infra --wait`:
   - Waits for `http://127.0.0.1:{authentik_port}/-/health/ready/` (30 × 5s retry)
   - Prints admin URL + bootstrap credentials hint

The blueprint engine auto-reapplies every reconcile cycle, so `authentik_bootstrap_password` and every OIDC `client_secret` drift through prefix rotation without DB surgery.

## Requirements

- Docker Desktop for Mac (ARM64)
- PostgreSQL + Redis running in the same infra compose project (`install_postgresql`, `redis_docker`)
- `stacks_shared_network` external network already created at play level
- `authentik_oidc_apps` / `authentik_default_groups` / `authentik_rbac_tiers` / `authentik_app_tiers` lists in `default.config.yml` — the central OIDC registry stays there so other services' compose fragments can read derived vars like `authentik_oidc_grafana_client_id`
- Play-level handlers `Restart authentik` and `Reapply authentik blueprints` (also provided role-local as a fallback)

## Variables

| Variable | Default | Description |
|---|---|---|
| `authentik_version` | `2025.12.4` | Pinned for CVE-2026-25227 (CVSS 9.1 code injection) |
| `authentik_port` | `9003` | Exposed on `127.0.0.1` only (9000 = PHP-FPM, 9001 = RustFS, 9002 = Portainer) |
| `authentik_domain` | `auth.dev.local` | Public domain behind nginx reverse proxy |
| `authentik_data_dir` | `~/authentik` | Host bind mount for `media`, `templates`, `certs` |
| `authentik_db_name` | `authentik` | PostgreSQL database name |
| `authentik_db_user` | `authentik` | PostgreSQL user |
| `authentik_mem_limit` | `{{ docker_mem_limit_critical }}` | Server memory limit (default `2g`) |
| `authentik_worker_mem_limit` | `{{ docker_mem_limit_standard }}` | Worker memory limit (default `1g`) |
| `authentik_cpus` | `{{ docker_cpus_standard }}` | Both containers (default `1.0`) |
| `authentik_secret_key` | *(from credentials)* | Prefix-rotated |
| `authentik_db_password` | *(from credentials)* | Prefix-rotated |
| `authentik_bootstrap_password` | *(from credentials)* | Initial admin password, re-applied by blueprint |
| `authentik_bootstrap_email` | `{{ default_admin_email }}` | Initial admin email |

Secrets and the OIDC registry stay in the top-level `default.config.yml` / `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work across all services.

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocations on `install_authentik`:

```yaml
# Before infra compose up
- name: "[Core] Authentik render + blueprints (pazny.authentik role)"
  ansible.builtin.include_role:
    name: pazny.authentik
  when: install_authentik | default(false)

# ... core-up.yml renders base infra compose + runs docker compose up ...

# After infra compose up
- name: "[Core] Authentik post-start health-check"
  ansible.builtin.include_role:
    name: pazny.authentik
    tasks_from: post.yml
  when:
    - install_authentik | default(false)
    - _core_infra_enabled | bool
```

Service-side OIDC wiring (Gitea Admin API, Nextcloud `occ user_oidc`, Portainer UI) stays in `tasks/stacks/authentik_service_post.yml` and runs later in `stack-up.yml`.

## Rollback

Revert the commit that introduced this role and:

1. Restore the `authentik-server` + `authentik-worker` service blocks in `templates/stacks/infra/docker-compose.yml.j2`
2. Restore `tasks/stacks/authentik_blueprints.yml`, `templates/authentik/blueprints/*.yaml.j2`, and `tasks/stacks/authentik_post.yml`
3. Restore the `include_tasks` / `include_role` calls in `tasks/stacks/core-up.yml`

The override file at `~/stacks/infra/overrides/authentik.yml` becomes dead — delete it manually if the rollback is permanent.
