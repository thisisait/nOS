# WordPress

> CMS for web content. Manages pages, posts and media.

## Quick Reference

| | |
|---|---|
| **URL** | `https://wordpress{host_alias_seg}.{tenant_domain}` (default `https://wordpress.dev.local`) |
| **Port** | `8084` (`wordpress_port`; loopback publish `127.0.0.1:8084` → container `80`) |
| **Stack** | `iiab` |
| **Toggle** | `install_wordpress: true` (default `false`) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` (role fragment: `~/stacks/iiab/overrides/wordpress.yml`) |
| **Image** | `wordpress:6.9.4` (`wordpress_version`) |
| **Data** | `{{ wordpress_dir }}` — default `~/projects/wordpress` → `/var/www/html` |
| **mu-plugins** | `~/stacks/iiab/wordpress/mu-plugins` → `/var/www/html/wp-content/mu-plugins` (read-only) |
| **Mem / CPU** | `wordpress_mem_limit` (default `1g`) / `1.0` |

**WordPress is the exception to the `nos_data_root` scheme.** Its var is `wordpress_dir`
(not `wordpress_data_dir`), and it points at `~/projects/wordpress` — the whole webroot,
core files and `wp-content` together. `tasks/stacks/external-paths.yml` relocates it to
`{{ external_storage_root }}/wordpress` on external storage. Posts, pages, and users are
rows in **MariaDB**; this directory holds core, themes, plugins, and uploads.

The mu-plugins mount is *config*, so it correctly stays under `~/stacks/`. It is mounted
as a **directory, not individual files**: on a fresh install `wp-content/mu-plugins` does
not exist yet, and Docker cannot create single-file bind mountpoints inside a VirtioFS
volume — it fails with "mountpoint … is outside of rootfs" and takes the whole iiab
stack-up down with it. The role stages `oidc-bootstrap.php` always, plus the devlog
app-passwords, RBAC role-sync, CVE-2026-63030 batch-block, and unauth-hardening
mu-plugins conditionally.

**The version pin is a hold, not a preference.** `6.9.4` is inside the wp2shell CVE range
(CVE-2026-63030 + CVE-2026-60137, unauth RCE); upstream fixed it in 6.8.6 / 6.9.5 / 7.0.2
and the Docker official image ships none of the three. So the pin stays and
`wordpress_cve_63030_mitigate: true` unregisters `/wp-json/batch/v1/` via mu-plugin.
Do **not** bump to 7.0.0/7.0.1 — they are newer but in the same CVE range.

## Authentication

- **Admin user:** `admin` (`wordpress_admin_user`)
- **Admin password:** `{global_password_prefix}_pw_wordpress_admin` (`wordpress_admin_password`).
  Note the suffix: `{prefix}_pw_wordpress` **without** `_admin` is the *database*
  password (`wordpress_db_password`) — different secret.
- **SSO:** `native_oidc` (Authentik OAuth2 client `nos-wordpress`, slug `wordpress`), RBAC tier **4**.
  - Redirect URI: `https://{wordpress_domain}/wp-admin/admin-ajax.php?action=openid-connect-authorize`
  - Scopes: `openid`, `email`, `profile`
  - Delivered by the `openid-connect-generic` plugin, configured from `WP_OIDC_*` env by
    the `oidc-bootstrap.php` mu-plugin. Autologin is `partial`: `WP_OIDC_LOGIN_TYPE=auto-sso`
    auto-redirects but does **not** hide the form — `/wp-login.php` stays directly
    reachable and is the documented break-glass.

## API Access

- **Base URL:** `https://wordpress.dev.local/wp-json/wp/v2/`
- **Auth method:** Basic auth (Application Passwords)
- **Bot account:** `nos-devlog-bot` — created by `roles/pazny.wordpress/tasks/devlog.yml`
  with the **author** role (`wordpress_devlog_bot_user`). Author can publish and edit its
  own posts but cannot create terms, which is deliberate: it avoids handing the bot editor
  rights over the operator's posts. The role then grants exactly one extra capability,
  `manage_categories` — without it the sync's ensure-category / ensure-tags REST calls
  `403` (caught on the first live run, 2026-06-12).
- **Token location:** `~/.nos/secrets.yml` as `wordpress_devlog_app_password` (an
  Application Password named `nos-devlog`, `wordpress_devlog_app_name`). Consumed by
  `tools/devlog-post.py` and `tasks/devlog-sync.yml`. Nothing writes
  `~/agents/tokens/wordpress.token`.

## Health Check

- **Endpoint:** `GET /` — the container healthcheck curls `http://localhost:80/`; the
  plugin's `wait_health` probes `/wp-login.php`. A fresh install `302`s to the installer,
  which is `<400`, so `curl -f` passes once Apache serves.
- **Expected:** `2xx`/`3xx`
- Note the image ships `curl` but **not** `wp-cli` (that is the `wordpress:cli` image);
  the role reaches wp-cli through `docker compose exec`.

## Dependencies

- MariaDB (posts / pages / users — required; DB `wordpress`, user `wordpress`, prefix `wp_`)
- Authentik (native-OIDC SSO — optional)
