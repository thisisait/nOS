# pazny.miniflux — Integration checklist

This role is **not** wired into the playbook by default. Apply the following
patches to the shared configuration + orchestrators.

## 1. `default.config.yml` — IIAB section (after `install_calibreweb`)

```yaml
install_miniflux: false           # Miniflux - minimalist RSS reader               [requires: PostgreSQL, Docker]
```

## 2. `default.config.yml` — `authentik_oidc_apps` (native OIDC entry)

Add to the native-OIDC block (near the Outline entry, NOT in the proxy block):

```yaml
  - name: "Miniflux"
    slug: "miniflux"
    enabled: "{{ install_miniflux | default(false) }}"
    client_id: "nos-miniflux"
    client_secret: "{{ global_password_prefix }}_pw_oidc_miniflux"
    redirect_uris: "https://{{ miniflux_domain | default('rss.dev.local') }}/oauth2/oidc/callback"
    launch_url: "https://{{ miniflux_domain | default('rss.dev.local') }}"
```

## 3. `default.config.yml` — helper vars (after `authentik_oidc_gitlab_*`)

```yaml
authentik_oidc_miniflux_client_id: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', 'miniflux') | first).client_id }}"
authentik_oidc_miniflux_client_secret: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', 'miniflux') | first).client_secret }}"
```

## 4. `default.config.yml` — `authentik_app_tiers` (Tier 3 — user)

Add under the existing Tier 3 block:

```yaml
authentik_app_tiers:
  ...
  miniflux: 3
```

## 5. `default.credentials.yml` — append new block

```yaml
# ==============================================================================
# MINIFLUX (only when install_miniflux: true)
# Default login: admin / miniflux_admin_password (fallback) or Authentik SSO
# Requires: PostgreSQL
# ==============================================================================

miniflux_db_password: "{{ global_password_prefix }}_pw_miniflux"
miniflux_admin_password: "{{ global_password_prefix }}_pw_miniflux_admin"
```

## 6. PostgreSQL provisioning — `roles/pazny.postgresql/tasks/post.yml`

The DB/user/pgcrypto/grant loops in `pazny.postgresql/tasks/post.yml` must
include miniflux. Extend each of the four loops (drop-role, create-db,
create-user, enable-pgcrypto, grant-privileges) with a conditional entry:

```yaml
+ ((install_miniflux | default(false)) | ternary(
    [{'user': miniflux_db_user | default('miniflux'), 'pass': miniflux_db_password | default(global_password_prefix + '_pw_miniflux')}], []))
```

(a logically equivalent `{'db': 'miniflux', 'user': 'miniflux'}` variant goes
into the create-db / pgcrypto / grant loops). Equivalent to the brief's
"Postgres DB provision entry":

```yaml
{ name: "miniflux DB", db: "miniflux", owner: "miniflux", password: "{{ miniflux_db_password }}" }
```

## 7. `tasks/stacks/stack-up.yml` — render snippet

Inside the `# IIAB roles` block, after `pazny.calibre_web`:

```yaml
- { name: "[Stacks] pazny.miniflux render", ansible.builtin.include_role: { name: pazny.miniflux, apply: { tags: ['miniflux'] } }, when: "install_miniflux | default(false)", tags: ['miniflux'] }
```

No post-start role call is needed — native OIDC uses env vars and Authentik's
service-side setup is already handled by the existing
`authentik_service_post.yml` (for proxy apps) / native env-var flow.

## 8. (Optional) `tasks/stacks/external-paths.yml`

If external SSD storage is in use, add:

```yaml
miniflux_data_dir: "{{ external_storage_root }}/miniflux/data"
```

## 9. (Optional) Nginx vhost auto-enable

Nginx vhost (`templates/nginx/sites-available/miniflux.conf`) follows the
naming convention — auto-enabled based on `install_miniflux`. No manual
`nginx_sites_enabled` change needed if the role-aware auto-enable matcher in
`tasks/nginx.yml` handles it; otherwise add `miniflux.conf` to
`nginx_sites_extra`.

## 10. Smoke test

```bash
# Syntax check
ansible-playbook main.yml --syntax-check

# Deploy only miniflux (assumes infra is up)
ansible-playbook main.yml -K --tags "stacks,miniflux,nginx" -e install_miniflux=true

# Container health
docker compose -p iiab ps miniflux
docker compose -p iiab logs --tail=50 miniflux

# HTTP + OIDC endpoint
curl -k -I https://rss.dev.local
curl -k https://rss.dev.local/healthcheck         # → "OK"
curl -k https://rss.dev.local/metrics | head      # Prometheus exposition

# OIDC discovery reachable from inside container
docker compose -p iiab exec miniflux wget -qO- \
  https://auth.dev.local/application/o/miniflux/.well-known/openid-configuration \
  | head -5
```
