# pazny.n8n

Ansible role for deploying **n8n** (workflow automation) as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates `{{ n8n_data_dir }}` and the shared agent log directory on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/n8n.yml`
   - Enables the nginx vhost symlink (`{{ homebrew_prefix }}/etc/nginx/sites-enabled/n8n.conf`)
   - Notifies `Restart n8n` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Waits for `/healthz` to return 200
   - Runs `/api/v1/owner/setup` on first run
   - On subsequent runs, performs a session-based password reconverge via `/rest/login` + `/rest/change-password` using `previous_password_prefix` as the OLD credential

## Requirements

- Docker Desktop for Mac (ARM64)
- `stacks_shared_network` defined at the play level; `iiab_net` defined in the base `templates/stacks/iiab/docker-compose.yml.j2`
- The n8n nginx vhost template needs to already exist in `sites-available/` (rendered by the top-level `nginx` task)

## Variables

| Variable | Default | Description |
|---|---|---|
| `n8n_version` | `2.14.1` | Pinned for CVE-2026-33660/33696/33663/33713 |
| `n8n_port` | `5678` | Exposed on `127.0.0.1` only |
| `n8n_domain` | `n8n.dev.local` | Public URL |
| `n8n_data_dir` | `~/n8n` | Host bind mount for `/home/node/.n8n` |
| `n8n_timezone` | `Europe/Prague` | TZ env var |
| `n8n_admin_email` | `{{ default_admin_email }}` | Owner email (from top-level config) |
| `n8n_admin_password` | *(from credentials)* | Reconverged every run via `/rest/change-password` |
| `n8n_admin_firstname` | `Admin` | Owner first name |
| `n8n_admin_lastname` | `devBoxNOS` | Owner last name |
| `n8n_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Rollback

Revert the commit that introduced this role and:

1. Restore the n8n service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/n8n.yml` and `tasks/iiab/n8n_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/n8n.yml` becomes dead — delete it manually if the rollback is permanent.
