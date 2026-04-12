# pazny.traefik

Ansible role for deploying **Traefik** as a compose override fragment in the devBoxNOS `infra` stack. Reverse proxy / Docker ingress with dynamic service discovery via docker-socket-proxy.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction (infra-edge unit).

## What it does

Single invocation mode from `tasks/stacks/core-up.yml`:

- **Main (`tasks/main.yml`)** — runs *before* `docker compose up infra`:
  - Creates `{{ traefik_config_dir }}` and `conf.d/` on the host
  - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/infra/overrides/traefik.yml`
  - The override is picked up by core-up's `find + -f` loop and merged into the infra compose project
  - Notifies `Restart traefik` if the override template changed

No post-start task — Traefik is stateless, picks up dynamic config from the bind-mounted `conf.d/` directory on startup. The static `traefik.yml` configuration file is rendered by `tasks/iiab/traefik.yml` before core-up (legacy path, migration to role is Wave 3).

## Requirements

- Docker Desktop for Mac (ARM64)
- `docker-socket-proxy` service declared in the base `templates/stacks/infra/docker-compose.yml.j2` (shared with Portainer — gate is `install_portainer | install_traefik`)
- `stacks_shared_network` defined at the play level

## Variables

| Variable | Default | Description |
|---|---|---|
| `traefik_image_version` | `v3.6.12` | Pinned for CVE-2026-33186 (gRPC auth bypass) + CVE-2026-33433 (BasicAuth spoofing) |
| `traefik_http_port` | `80` | Only exposed when `install_nginx=false` |
| `traefik_https_port` | `443` | Only exposed when `install_nginx=false` |
| `traefik_dashboard_port` | `8080` | Insecure dashboard on `127.0.0.1` |
| `traefik_domain` | `traefik.dev.local` | Public domain for the dashboard |
| `traefik_log_level` | `INFO` | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `traefik_config_dir` | `~/iiab/traefik` | Host bind mount for `traefik.yml` + `conf.d/` |
| `traefik_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |
| `traefik_cpus` | `{{ docker_cpus_standard }}` | Defaults to `1.0` |

## Usage

From `tasks/stacks/core-up.yml`, gate the role invocation on `install_traefik`:

```yaml
- name: "[Core] Traefik render (pazny.traefik role)"
  ansible.builtin.include_role:
    name: pazny.traefik
  when: install_traefik | default(false)
```

## Rollback

Revert the commit that introduced this role and restore the `traefik` service block in `templates/stacks/infra/docker-compose.yml.j2`. The override file at `~/stacks/infra/overrides/traefik.yml` becomes dead — delete it manually if the rollback is permanent.
