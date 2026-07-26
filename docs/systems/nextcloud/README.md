# Nextcloud

> Self-hosted cloud — files, sharing, calendar, contacts, collaboration. Two host binds
> (app tree vs user data) plus a MariaDB schema; the split matters for backup and blank.

## Quick Reference

| | |
|---|---|
| **URL** | `https://cloud{host_alias_seg}.{tenant_domain}` (default `https://cloud.dev.local`) |
| **Port** | `8085` (`nextcloud_port`; loopback publish `127.0.0.1:8085` → container `80`; LAN publish only when `services_lan_access: true`) |
| **Stack** | `iiab` |
| **Node id** | `nos.iiab.nextcloud` |
| **Toggle** | `install_nextcloud: true` |
| **Image** | `nextcloud:33` (`nextcloud_version`; MAJOR-LOCKED on purpose — a floating `stable` that crosses a major 500s on existing data) |
| **Compose** | `~/stacks/iiab/docker-compose.yml` + `~/stacks/iiab/overrides/nextcloud.yml` (role) + `~/stacks/iiab/overrides/nextcloud-base.yml` (plugin extension) |
| **Container** | `iiab-nextcloud-1` |
| **App tree** | `~/projects/nextcloud` (`nextcloud_dir`) → `/var/www/html` — code, apps, and `config/config.php`. NOT user data |
| **Data** | `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/nextcloud/data` (default `~/nos/tenants/dev/shared/nextcloud/data`) → `/data` — tenant-shared user files (`NEXTCLOUD_DATA_DIR: /data`) |
| **Database** | MariaDB schema `nextcloud` on `infra-mariadb-1` (user `nextcloud`) — metadata, shares, users. NOT a volume, NOT on the filesystem |
| **Memory limit** | `2g` (`docker_mem_limit_critical`) |
| **Networks** | `iiab_net` + `shared_net` (`stacks_shared_network`) |
| **Coexistence** | supported (`state/manifest.yml`) |

`nextcloud_domain`, `nextcloud_port`, `nextcloud_version`, `nextcloud_dir`,
`nextcloud_data_dir` pin in `default.config.yml`; role defaults mirror them as
fallbacks. The domain derives from `tenant_domain` + `host_alias`, not a hardcoded
`dev.local`.

> **Config vs data — the split is load-bearing.** `nextcloud_dir` is the *config-class*
> bind (the PHP app tree; `roles/pazny.nextcloud/tasks/post.yml` edits `{{ nextcloud_dir }}/config/config.php`
> directly). It intentionally lives OUTSIDE the `nos_data_root` tree at
> `~/projects/nextcloud`. `nextcloud_data_dir` is the *data-class* bind and is
> tenant-shared (class 2) under `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/`,
> pinned by `tests/anatomy/test_fs_doctrine_paths.py`. Wiping one without the other
> leaves a half-installed Nextcloud.

**External-storage override:** `tasks/stacks/external-paths.yml` re-points BOTH —
`nextcloud_dir` → `{{ external_storage_root }}/nextcloud` and `nextcloud_data_dir` →
`{{ external_storage_root }}/nextcloud-data`.

**Compose config lives at `~/stacks/`** and that is current — only the DATA row moved to
`nos_data_root`.

## Authentication

- **Admin user:** `admin` (`nextcloud_admin_user` → `NEXTCLOUD_ADMIN_USER`)
- **Admin password:** `{global_password_prefix}_pw_nextcloud_admin`
  (`nextcloud_admin_password`). Reconverged on every run via
  `occ user:resetpassword --password-from-env`.
  - **Not** `{global_password_prefix}_pw_nextcloud` — that value is
    `nextcloud_db_password`, the MariaDB credential, and is a different secret.
- **SSO:** `native_oidc` — Authentik OAuth2 client `nos-nextcloud`, RBAC tier 3.
  Configured **via the `occ` CLI post-up** (`post_setup: nextcloud_occ`), NOT via compose
  env vars; the `nextcloud-base` plugin carries only the mkcert CA mount and the
  `auth.<tld>:host-gateway` alias.
  - Redirect URI: `https://{nextcloud_domain}/apps/user_oidc/code`
  - Scopes: `openid`, `profile`, `email`
- **Autologin:** supported, but only through `occ`
  (`user_oidc allow_multiple_user_backends=0` + `login_redirect=authentik`) — a compose
  env var alone cannot do it. Dormant behind `sso_autologin=false`.
  Break-glass: `?direct=1` always reaches Nextcloud's own login form.

## API Access

- **OCS API:** `https://{nextcloud_domain}/ocs/v2.php/` — requires header
  `OCS-APIRequest: true`
- **WebDAV:** `https://{nextcloud_domain}/remote.php/dav/`
- **Auth method:** Basic auth with an **App Password** the operator generates in
  Settings → Security for a real account. nOS provisions no service account and no
  token file — see `SKILLS.md`.
- **Operator CLI:** `docker compose -p iiab exec -T -u www-data nextcloud php occ <cmd>`
  — the exact invocation `roles/pazny.nextcloud/tasks/post.yml` uses, and the
  authoritative configuration path (OIDC, trusted domains, passwords all go through it).

## Health Check

- **Endpoint:** `GET /status.php` → `200 OK` with
  `{"installed":true,"maintenance":false,...}`
- **Container healthcheck:** `curl -fsS http://localhost:80/status.php` (interval 30s,
  retries 5, start period **120s** — a cold-blank first-boot install + DB migration runs
  60–120s).
- The plugin `post_compose` health-wait polls `http://127.0.0.1:8085/status.php`.

## Operator notes

- **IPv6 is disabled in the container** (`net.ipv6.conf.*.disable_ipv6=1`). The
  `auth.<tld>:host-gateway` alias resolves to a working IPv4 *and* a dead IPv6;
  `user_oidc` discovery intermittently picked the IPv6 and failed login with "Could not
  reach the OpenID Connect provider".
- **Trusted proxies** (`nextcloud_trusted_proxies`: `172.16/12`, `192.168/16`, `10/8`)
  must stay set, or Nextcloud sees one Docker gateway IP for the whole fleet and
  brute-force-429s the operator.
- **ONLYOFFICE / euro-office** is wired by `roles/pazny.nextcloud/tasks/post.yml` (`occ app:install onlyoffice`
  + `DocumentServerInternalUrl` over the shared network). `nextcloud` is added as a
  trusted domain so the docserver's download callback is accepted.

## Dependencies

- MariaDB (schema `nextcloud`) — required
- Authentik (native-OIDC SSO via `occ`) — optional
- ONLYOFFICE / euro-office (embedded editing) — optional
- Mailpit (SMTP relay when `install_mailpit` is on) — optional
