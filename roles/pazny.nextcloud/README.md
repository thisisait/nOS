# pazny.nextcloud

Ansible role for deploying **Nextcloud** as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates `{{ nextcloud_dir }}` and `{{ nextcloud_data_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/nextcloud.yml`
   - Renders the nginx vhost from the shared `templates/nginx/sites-available/nextcloud.conf`
   - Notifies `Restart nextcloud` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Syncs the DB password in `config.php` via `occ config:system:set dbpassword` (env var is only read on first init)
   - Reconverges admin password via `occ user:resetpassword --password-from-env`
   - Ensures `trusted_domains` array contains the canonical domain plus LAN/Tailscale extras
   - Enables `user_oidc` as the direct login when Authentik is installed

## Requirements

- Docker Desktop for Mac (ARM64)
- A running MariaDB (pazny.mariadb role) on the shared network
- `stacks_shared_network` defined at the play level; `iiab_net` defined in the base `templates/stacks/iiab/docker-compose.yml.j2`

## Variables

| Variable | Default | Description |
|---|---|---|
| `nextcloud_version` | `stable` | Docker image tag |
| `nextcloud_port` | `8085` | Exposed on `127.0.0.1` only |
| `nextcloud_domain` | `cloud.dev.local` | Public URL |
| `nextcloud_dir` | `~/projects/nextcloud` | Host bind mount for `/var/www/html` |
| `nextcloud_data_dir` | `~/nextcloud-data` | Host bind mount for `/data` |
| `nextcloud_db_name` | `nextcloud` | MySQL database name |
| `nextcloud_db_user` | `nextcloud` | MySQL user |
| `nextcloud_db_password` | *(from credentials)* | Set via `global_password_prefix` rotation |
| `nextcloud_db_host` | `127.0.0.1` | Ignored when `install_mariadb=true` (falls back to `mariadb`) |
| `nextcloud_admin_user` | `admin` | Admin username |
| `nextcloud_admin_password` | *(from credentials)* | Reconverged every run via `occ user:resetpassword` |
| `nextcloud_mem_limit` | `{{ docker_mem_limit_critical }}` | Defaults to `2g` |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Rollback

Revert the commit that introduced this role and:

1. Restore the nextcloud service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/nextcloud.yml` and `tasks/iiab/nextcloud_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/nextcloud.yml` becomes dead — delete it manually if the rollback is permanent.
