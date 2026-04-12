# pazny.wordpress

Ansible role for deploying **WordPress** as a compose override fragment in the devBoxNOS `iiab` stack.

Part of [devBoxNOS](../../README.md) Wave 2.2 role extraction.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates `{{ wordpress_dir }}` on the host
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/wordpress.yml`
   - Renders the nginx vhost from the shared `templates/nginx/sites-available/wordpress.conf`
   - Notifies `Restart wordpress` if the override template changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Detects if the container is running
   - Installs `wp-cli` inside the container (first run only)
   - Runs `wp core install` on first run
   - On subsequent runs, calls `wp user update --user_pass` to reconverge the admin password from `global_password_prefix`

## Requirements

- Docker Desktop for Mac (ARM64)
- A running MariaDB (pazny.mariadb role) on the shared network — WordPress resolves the host by the `mariadb` service name.
- `stacks_shared_network` defined at the play level; `iiab_net` defined in the base `templates/stacks/iiab/docker-compose.yml.j2`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `wordpress_version` | `latest` | Docker image tag |
| `wordpress_port` | `8084` | Exposed on `127.0.0.1` only |
| `wordpress_domain` | `wordpress.dev.local` | Public URL for the site |
| `wordpress_dir` | `~/projects/wordpress` | Host bind mount for `/var/www/html` |
| `wordpress_db_name` | `wordpress` | MySQL database name |
| `wordpress_db_user` | `wordpress` | MySQL user |
| `wordpress_db_password` | *(from credentials)* | Set via `global_password_prefix` rotation |
| `wordpress_db_host` | `127.0.0.1` | Ignored when `install_mariadb=true` (falls back to `mariadb`) |
| `wordpress_table_prefix` | `wp_` | WordPress table prefix |
| `wordpress_admin_user` | `admin` | WordPress admin username |
| `wordpress_admin_password` | *(from credentials)* | Reconverged every run via `wp user update` |
| `wordpress_admin_email` | `{{ default_admin_email }}` | Admin email |
| `wordpress_mem_limit` | `{{ docker_mem_limit_standard }}` | Defaults to `1g` |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Rollback

Revert the commit that introduced this role and:

1. Restore the wordpress service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/wordpress.yml` and `tasks/iiab/wordpress_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/wordpress.yml` becomes dead — delete it manually if the rollback is permanent.
