# pazny.puter

Ansible role for deploying **Puter** (cloud OS web desktop) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

## What it does

Three task entry points:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates `{{ puter_data_dir }}` and `{{ puter_config_dir }}`
   - Renders the shared `templates/puter/config.json.j2` (Dockerfile-backed build context stays in `{{ playbook_dir }}/files/puter/`)
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/puter.yml`
   - At the end, `include_tasks: apps.yml` is called — `apps.yml` itself is gated by a healthcheck to `/healthcheck` with the Puter Host header, so it is a no-op until the container is running
   - Notifies `Restart puter` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Removes cloud-only stock apps (camera, editor, player, recorder, viewer, pdf)
   - Waits for the `/healthcheck` endpoint to come up
   - Detects whether the `admin` user row exists in the bundled SQLite database
   - Creates the admin user on first run (bcrypt via bundled `bcryptjs`, random UUID)
   - On subsequent runs, reconverges the admin password via a bcrypt `UPDATE user` statement

3. **Apps (`tasks/apps.yml`)** — registers every enabled devBoxNOS service as an iframe app in the Puter Start menu. Idempotent — existing app rows are skipped. Called via `include_tasks` from `main.yml`.

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level; `iiab_net` defined in the base `templates/stacks/iiab/docker-compose.yml.j2`
- `templates/puter/config.json.j2` and `files/puter/Dockerfile` must exist in the playbook (kept in-tree for the Docker build context)

## Variables

| Variable | Default | Description |
|---|---|---|
| `puter_version` | `latest` | Docker image tag — built locally as `devboxnos/puter:<tag>` |
| `puter_port` | `5050` | Exposed on `127.0.0.1` only (maps to container `4100`) |
| `puter_domain` | `os.dev.local` | Public URL |
| `puter_api_domain` | `api.os.dev.local` | API subdomain |
| `puter_data_dir` | `~/puter` | Host bind mount for `/var/puter` |
| `puter_config_dir` | `~/puter/config` | Host bind mount for `/etc/puter` |
| `puter_file_cache_mb` | `512` | File cache for multi-user storage |
| `puter_admin_email` | `{{ default_admin_email }}` | Admin email |
| `puter_admin_password` | *(from credentials)* | Reconverged every run via bcrypt `UPDATE` |
| `puter_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Rollback

Revert the commit that introduced this role and:

1. Restore the puter service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/puter.yml`, `tasks/iiab/puter_post.yml` and `tasks/iiab/puter_apps.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/puter.yml` becomes dead — delete it manually if the rollback is permanent.
