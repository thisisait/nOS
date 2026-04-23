# pazny.wordpress

Ansible role for deploying **WordPress** as a compose override fragment in the nOS `iiab` stack.

Part of [nOS](../../README.md) Wave 2.2 role extraction.

## What it does

Two invocation modes from `tasks/stacks/stack-up.yml`:

1. **Main (`tasks/main.yml`)** — runs *before* `docker compose -p iiab up`:
   - Creates `{{ wordpress_dir }}` on the host
   - Stages the OIDC mu-plugin (`files/oidc-mu-plugin.php`) into `{{ stacks_dir }}/iiab/wordpress/mu-plugins/oidc-bootstrap.php`
   - Renders `templates/compose.yml.j2` into `{{ stacks_dir }}/iiab/overrides/wordpress.yml` (mounts the mu-plugin into `wp-content/mu-plugins/`)
   - Renders the nginx vhost from the shared `templates/nginx/sites-available/wordpress.conf`
   - Notifies `Restart wordpress` if the override template or mu-plugin changed

2. **Post (`tasks/post.yml`)** — runs *after* `docker compose -p iiab up`:
   - Detects if the container is running
   - Installs `wp-cli` inside the container (first run only)
   - Runs `wp core install` on first run
   - On subsequent runs, calls `wp user update --user_pass` to reconverge the admin password from `global_password_prefix`
   - When `install_authentik=true`, runs `wp plugin install daggerhart-openid-connect-generic --activate` (idempotent)

## SSO — native OIDC via `openid-connect-generic`

WordPress core has no OIDC support. nOS installs the community
[openid-connect-generic](https://wordpress.org/plugins/daggerhart-openid-connect-generic/)
plugin via `wp-cli` in `post.yml` and configures it from the compose env vars
through a must-use plugin (`wp-content/mu-plugins/oidc-bootstrap.php`). The
mu-plugin auto-loads on every request and reconciles
`openid_connect_generic_settings` with whatever Ansible pushed — state-declarative,
no manual `/wp-admin` configuration needed.

Flow:

1. Compose env (`WP_OIDC_*`) supplies `client_id`, `client_secret`, and endpoints
   derived from `authentik_oidc_apps` (slug `wordpress`).
2. `post.yml` installs + activates `openid-connect-generic` (no-op when already
   installed).
3. The mu-plugin (`oidc-bootstrap.php`) pushes the settings into WP options on
   the next request.
4. Login UI at `/wp-login.php` shows a "Sign in with Authentik" button
   (`login_type=button`); set `wordpress_oidc_login_type=auto` for
   auto-redirect-to-SSO.

Redirect URI registered with Authentik:
`https://{{ wordpress_domain }}/wp-admin/admin-ajax.php?action=openid-connect-authorize`

Proxy-auth / `forward_auth` is intentionally NOT used — the nginx vhost is a
plain reverse proxy, which gives WP real user objects (with roles, author
attribution, REST API calls) rather than an opaque Authentik header.

## Requirements

- Docker Desktop for Mac (ARM64)
- A running MariaDB (pazny.mariadb role) on the shared network — WordPress resolves the host by the `mariadb` service name.
- `stacks_shared_network` defined at the play level; `iiab_net` defined in the base `templates/stacks/iiab/docker-compose.yml.j2`.
- When `install_authentik=true`: an `authentik_oidc_apps` entry with `slug: wordpress`, providing `authentik_oidc_wordpress_client_id` and `authentik_oidc_wordpress_client_secret`.

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
| `wordpress_oidc_login_type` | `button` | `button` renders an SSO button on wp-login; `auto` redirects immediately |

Secrets stay in the top-level `default.credentials.yml` so the blank-reset prefix rotation pattern continues to work.

## Rollback

Revert the commit that introduced this role and:

1. Restore the wordpress service block in `templates/stacks/iiab/docker-compose.yml.j2`
2. Restore `tasks/iiab/wordpress.yml` and `tasks/iiab/wordpress_post.yml`
3. Restore the `import_tasks` calls in `main.yml`

The override file at `~/stacks/iiab/overrides/wordpress.yml` becomes dead — delete it manually if the rollback is permanent.

To roll back just the native-OIDC migration (keep the role, keep proxy-auth):

1. Revert `templates/nginx/sites-available/wordpress.conf` to the `forward_auth` version.
2. Drop the `WP_OIDC_*` env block from `roles/pazny.wordpress/templates/compose.yml.j2`.
3. Delete `~/stacks/iiab/wordpress/mu-plugins/oidc-bootstrap.php` and `docker compose -p iiab restart wordpress`.
4. `wp plugin deactivate daggerhart-openid-connect-generic` inside the container.
