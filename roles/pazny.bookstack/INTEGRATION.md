# INTEGRATION: pazny.bookstack

Mechanical patches that the parent agent must apply after merging this role into `dev`.
No file outside `roles/pazny.bookstack/` and `templates/nginx/sites-available/bookstack.conf` was modified.

---

## 1. `default.config.yml` — install toggle

Insert into the B2B section (~line 148, after `install_outline:`):

```yaml
install_bookstack: false         # BookStack - wiki (Shelf/Book/Chapter/Page) [requires: MariaDB, Redis Docker]
```

## 2. `default.config.yml` — authentik_oidc_apps entry

Append to the `authentik_oidc_apps:` list (before the helper-vars block; see the `authentik_oidc_outline` entry as a template):

```yaml
  - name: "BookStack"
    slug: "bookstack"
    enabled: "{{ install_bookstack | default(false) }}"
    client_id: "nos-bookstack"
    client_secret: "{{ global_password_prefix }}_pw_oidc_bookstack"
    redirect_uris: "https://{{ bookstack_domain | default('bookstack.dev.local') }}/oidc/callback"
    launch_url: "https://{{ bookstack_domain | default('bookstack.dev.local') }}"
```

## 3. `default.config.yml` — helper vars (OIDC native)

Insert alongside the other `authentik_oidc_*_client_id` variables (after `authentik_oidc_gitlab_client_secret`, ~line 1657):

```yaml
authentik_oidc_bookstack_client_id: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', 'bookstack') | first).client_id }}"
authentik_oidc_bookstack_client_secret: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', 'bookstack') | first).client_secret }}"
```

## 4. `default.config.yml` — authentik_app_tiers entry

Add to `authentik_app_tiers:` among the tier-3 services (~line 1475):

```yaml
  bookstack: 3
```

## 5. `default.credentials.yml` — new secrets

Insert after `outline_utils_secret:` (~line 211):

```yaml
# ==============================================================================
# BOOKSTACK (only when install_bookstack: true)
# Default login: OIDC via Authentik (or local admin@admin.com / password on first init)
# Requires: MariaDB
# ==============================================================================

bookstack_db_password: "{{ global_password_prefix }}_pw_bookstack"
bookstack_app_key: "{{ global_password_prefix }}_pw_bookstack_app_key"   # overwritten in main.yml via openssl rand
```

## 6. `main.yml` — auto-generate APP_KEY

BookStack requires a Laravel-style `APP_KEY` in the format `base64:<32-byte-base64>`.
Add to the **"Auto-regenerate stateless secrets (every run — safe group)"** block (~line 372-380):

```yaml
        bookstack_app_key: "base64:{{ lookup('pipe', 'openssl rand -base64 32') }}"
```

> Note: This belongs to the **safe group** because APP_KEY only encrypts sessions / remember tokens and a reset merely forces re-login — persistent data (pages/books in DB) stays intact. If application-level encryption of other items is introduced later, move it to the destructive group.

## 7. `main.yml` — Redis auto-enable

Add `install_bookstack` to the `Auto-enable Redis Docker for services that require it` condition (~line 352-362):

```yaml
      when: >
        (install_authentik | default(false)) or
        (install_infisical | default(false)) or
        (install_jsos | default(false)) or
        (install_erpnext | default(false)) or
        (install_outline | default(false)) or
        (install_superset | default(false)) or
        (install_bookstack | default(false))
```

## 8. `default.config.yml` — MariaDB DB provision entries

In the **IIAB - MARIADB (continued)** block (~line 736-758):

`mariadb_databases:` — add:
```yaml
  - name: "bookstack"
```

`mariadb_users:` — add:
```yaml
  - name: "bookstack"
    password: "{{ bookstack_db_password }}"
    priv: "bookstack.*:ALL"
```

This causes DB + user to be created automatically in the `pazny.mariadb` post-start step in `tasks/stacks/core-up.yml` (invoked BEFORE the b2b stack starts).

## 9. `tasks/stacks/stack-up.yml` — role include

Insert into the **`# B2B roles`** block (~line 88-91, after `pazny.outline render`):

```yaml
- { name: "[Stacks] pazny.bookstack render", ansible.builtin.include_role: { name: pazny.bookstack, apply: { tags: ['bookstack'] } }, when: "install_bookstack | default(false)", tags: ['bookstack'] }
```

## 10. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update

In the `Build list of remaining (non-core) active stacks` set_fact (~line 109) extend the b2b condition:

```yaml
        ((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_bookstack | default(false)) | ternary(['b2b'], []))
```

## 11. `tasks/stacks/stack-up.yml` — b2b compose deploy condition

In the `[Stacks] Deploy b2b compose` task (~line 35-40) extend `when:`:

```yaml
  when: install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_bookstack | default(false)
```

## 12. `tasks/nginx.yml` — auto-enable vhost

In the `_nginx_sites_auto` set_fact (~line 107-144) add a line (e.g. after `outline.conf`):

```yaml
         + ((install_bookstack | default(false)) | ternary(['bookstack.conf'], []))
```

And to the template loop list (~line 80-84, after `freescout.conf`/`outline.conf`):

```yaml
    - bookstack.conf
```

## 13. Nginx vhost (documentation)

File: `templates/nginx/sites-available/bookstack.conf`
Activates automatically via `install_bookstack: true` (see section 12). Native OIDC — no `forward_auth`, no `authentik-proxy-auth` include. `client_max_body_size 50m` for BookStack gallery/cover uploads.

## 14. Smoke test

After `ansible-playbook main.yml -K -e install_bookstack=true --tags bookstack,b2b,mariadb` verify:

```bash
# container is running
docker ps | grep bookstack                         # Up, healthy

# HTTP 200/302 on login
curl -k -I https://bookstack.dev.local             # 302 -> /login or 200

# DB is reachable
docker compose -p infra exec mariadb \
  mariadb -u bookstack -p"${PREFIX}_pw_bookstack" -e 'SHOW DATABASES;' \
  | grep bookstack

# Authentik OIDC discovery endpoint (when install_authentik=true)
curl -k https://auth.dev.local/application/o/bookstack/.well-known/openid-configuration | jq .issuer

# OIDC login redirect (browser): https://bookstack.dev.local -> "Login with Authentik" button
```

## 15. Notes

- **Image version**: `lscr.io/linuxserver/bookstack:v26.03.3-ls256` (current stable at role creation time). To upgrade, override `bookstack_version` in `defaults/main.yml` or in `config.yml`.
- **Domain**: `bookstack.dev.local` — NOT `wiki.dev.local` (collides with Outline).
- **On first init (without OIDC)** BookStack ships with default admin `admin@admin.com` / `password`. When `install_authentik=true`, login goes through Authentik (OIDC users auto-register and are attached to Authentik groups).
- **OIDC scopes**: `openid profile email groups` — the `groups` scope requires an Authentik `Group Membership Scope Mapping` (typically already part of the `authentik_oidc_setup.yml` blueprint; if not, BookStack still works without `groups`, but `OIDC_USER_TO_GROUPS` will not map roles).
