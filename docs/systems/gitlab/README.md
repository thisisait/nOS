# GitLab

> Self-hosted GitLab CE — Git hosting, CI/CD, container registry, wiki and issues.
> Heavy Omnibus stack (~4 GB RAM at rest) in the `devops` compose project.
> In nOS it is the local agent MR review surface (T32.2); GitHub stays the public trunk.

## Quick Reference

| | |
|---|---|
| **Node** | `nos.devops.gitlab` |
| **Stack** | `devops` |
| **Toggle** | `install_gitlab: false` |
| **Image** | `gitlab/gitlab-ce:18.11.7-ce.0` |
| **Domain** | `gitlab.<tenant_domain>` (pattern `gitlab{{ _host_alias_seg }}.{{ tenant_domain }}`, `external_url` over HTTPS) |
| **HTTP port** | `8929` — published `127.0.0.1:8929` → container `80` |
| **SSH port** | `2224` — published `127.0.0.1:2224` → container `22` (`gitlab_shell_ssh_port`) |
| **Data** | `{{ nos_data_root }}/platform/services/gitlab/data` → `/var/opt/gitlab` |
| **Config** | `{{ nos_data_root }}/platform/services/gitlab/config` → `/etc/gitlab` |
| **Logs** | `{{ HOME }}/gitlab-logs` → `/var/log/gitlab` |
| **Mem limit** | `gitlab_mem_limit` (default `docker_mem_limit_heavy`, `4g`) |
| **Container** | `devops-gitlab-1` |

`nos_data_root` defaults to `{{ HOME }}/nos`; redirect it (e.g. onto an external SSD) and every path above moves with it.

## Authentication

- **Admin user:** `root`
- **Admin password:** `gitlab_admin_password` = `{global_password_prefix}_pw_gitlab` (converged into the running instance by `roles/pazny.gitlab/tasks/post.yml`; Omnibus otherwise auto-generates `/etc/gitlab/initial_root_password`).
- **Signup:** disabled (`gitlab_rails['gitlab_signup_enabled'] = false`).
- **SSO:** Authentik **native OIDC** (omniauth `openid_connect`). Client id `nos-gitlab`, secret `{global_password_prefix}_pw_oidc_gitlab`. Rendered only when `install_authentik` is true. RBAC tier **2** (manager). Users in the Tier-1 admin group are mapped to GitLab admin via `admin_groups`.

## API Access

- **Base (loopback):** `http://127.0.0.1:8929/api/v4/`
- **Base (routed):** `https://gitlab.<tenant_domain>/api/v4/`
- **Auth header:** `PRIVATE-TOKEN: <token>`
- **Agent PAT:** `gitlab_api_token` — a Personal Access Token minted **only when `gitlab_agent_forge: true`** by `roles/pazny.gitlab/tasks/post-forge.yml` (scopes `api`, `write_repository`), persisted to `{{ HOME }}/.nos/secrets.yml`. Absent when the forge is off.

## Health Check

- **Endpoint:** `GET /-/readiness` (manifest `health_check`, `http://localhost:{{ gitlab_http_port }}/-/readiness`, expect `200`).
- **In-container healthcheck:** `curl -sf http://localhost:80/-/readiness` (`start_period` 300s — cold init is slow).
- The Docker bridge is whitelisted (`gitlab_rails['monitoring_whitelist']`) so the host-side probe reaches `/-/readiness` instead of a 404.

## Dependencies

- Docker (`devops` compose stack), ~4 GB RAM.
- Authentik (SSO, optional — only when `install_authentik: true`).
- Bundled inside the Omnibus image (not shared nOS services): PostgreSQL, Redis, nginx. External Prometheus/exporters are disabled in the Omnibus config.

## Agent Forge (T32.2)

When `gitlab_agent_forge: true`, GitLab hosts the `root/nOS` project (created empty, private) as the operator-facing merge-request review surface. Agents open MRs against it via `tools/recipe-pr.sh --forge gitlab`; the operator host feeds trunk with `tools/sync-trunk-to-gitlab.sh` (fast-forward only). Members in `gitlab_forge_members` (default `akadmin`) are granted MAINTAINER.
