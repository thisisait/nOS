# INTEGRATION: pazny.hedgedoc

All patches are **declarative** — parent agent applies them to the listed files after merging this role.

## 1. `default.config.yml` — install toggle

Insert in the **B2B stack** block (after `install_outline` ~line 148):

```yaml
install_hedgedoc: false           # HedgeDoc - real-time collaborative markdown editor [requires: PostgreSQL]
```

## 2. `default.config.yml` — HedgeDoc variable block

Insert a new block (near the Outline block ~line 1220):

```yaml
# ==============================================================================
# B2B - HEDGEDOC (real-time collaborative markdown editor)
# Requires: install_postgresql: true
# ==============================================================================

hedgedoc_domain: "hedgedoc.{{ instance_tld | default('dev.local') }}"
hedgedoc_port: 3012
hedgedoc_version: "1.10.7"
hedgedoc_data_dir: "{{ ansible_facts['env']['HOME'] }}/hedgedoc/uploads"
hedgedoc_db_name: "hedgedoc"
hedgedoc_db_user: "hedgedoc"
hedgedoc_db_password: "{{ global_password_prefix }}_pw_hedgedoc"
hedgedoc_session_secret: "{{ global_password_prefix }}_pw_hedgedoc_session"
```

## 3. `default.config.yml` — authentik_oidc_apps entry

Append to `authentik_oidc_apps:` list (before helper vars block ~line 1614):

```yaml
  - name: "HedgeDoc"
    slug: "hedgedoc"
    enabled: "{{ install_hedgedoc | default(false) }}"
    client_id: "nos-hedgedoc"
    client_secret: "{{ global_password_prefix }}_pw_oidc_hedgedoc"
    redirect_uris: "https://{{ hedgedoc_domain | default('hedgedoc.dev.local') }}/auth/oauth2/callback"
    launch_url: "https://{{ hedgedoc_domain | default('hedgedoc.dev.local') }}"
```

## 4. `default.config.yml` — helper vars (native OIDC)

Insert near other `authentik_oidc_*_client_id` vars (~line 1614):

```yaml
authentik_oidc_hedgedoc_client_id: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', 'hedgedoc') | first).client_id }}"
authentik_oidc_hedgedoc_client_secret: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', 'hedgedoc') | first).client_secret }}"
```

## 5. `default.config.yml` — authentik_app_tiers entry

Add to `authentik_app_tiers:` (near `outline: 3` ~line 1438):

```yaml
  hedgedoc: 3
```

## 6. `default.credentials.yml` — new secrets

Insert after Outline credentials block (~line 211):

```yaml
# HEDGEDOC (only when install_hedgedoc: true)
hedgedoc_db_password: "{{ global_password_prefix }}_pw_hedgedoc"
hedgedoc_session_secret: "{{ global_password_prefix }}_pw_hedgedoc_session"
```

## 7. `main.yml` — auto-generate stateless secret (safe group)

Add to the **safe group** `set_fact` block (~line 372, next to `outline_utils_secret`):

```yaml
    - name: "Auto-regenerate stateless secrets (every run — safe group)"
      ansible.builtin.set_fact:
        # ... existing entries ...
        hedgedoc_session_secret: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
      tags: ['always']
```

Rationale: session cookies are re-issuable; notes are stored in Postgres, so rotating this secret only logs users out — no data loss.

## 8. `main.yml` — auto-enable PostgreSQL

Add `install_hedgedoc` to the `when:` list under **Auto-enable PostgreSQL** (~line 341):

```yaml
      when: >
        (install_authentik | default(false)) or
        ...
        (install_outline | default(false)) or
        (install_hedgedoc | default(false)) or
        (install_metabase | default(false)) or
        ...
```

(HedgeDoc does **not** need Redis — skip `redis_docker` block.)

## 9. `tasks/stacks/core-up.yml` — Postgres DB provisioning

In `roles/pazny.postgresql/tasks/post.yml`, add `hedgedoc` to the three list literals (`Drop existing databases on blank reset`, `Create databases`, `Enable pgcrypto in each service database`):

```yaml
{{ ['outline', 'metabase', 'superset', 'hedgedoc']
   + ((install_authentik | default(false)) | ternary([authentik_db_name | default('authentik')], []))
   ...
```

And to the DB-user creation loop (around the `outline_db_user` entry):

```yaml
         {'user': hedgedoc_db_user | default('hedgedoc'), 'pass': hedgedoc_db_password | default(global_password_prefix + '_pw_hedgedoc')},
```

And to the per-db owner map:

```yaml
         {'db': 'hedgedoc', 'user': hedgedoc_db_user | default('hedgedoc')},
```

> **Note:** alternative idiom per AGENT_BRIEF sec. 9 would be a single `{ name: "hedgedoc DB", db: "hedgedoc", owner: "hedgedoc", password: "{{ hedgedoc_db_password }}" }` entry — keep whichever pattern `pazny.postgresql/tasks/post.yml` is using at merge time.

## 10. `tasks/stacks/stack-up.yml` — role include

Insert in the **`# B2B roles`** block (after `pazny.outline render` ~line 91):

```yaml
- { name: "[Stacks] pazny.hedgedoc render", ansible.builtin.include_role: { name: pazny.hedgedoc, apply: { tags: ['hedgedoc'] } }, when: "install_hedgedoc | default(false)", tags: ['hedgedoc'] }
```

## 11. `tasks/stacks/stack-up.yml` — b2b stack activation

Update the **`[Stacks] Deploy b2b compose`** `when:` guard (~line 40):

```yaml
  when: install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_hedgedoc | default(false)
```

## 12. `tasks/stacks/stack-up.yml` — `_remaining_stacks` condition update

Update the B2B activation ternary (~line 109):

```yaml
        ((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_hedgedoc | default(false)) | ternary(['b2b'], []))
```

## 13. `tasks/stacks/external-paths.yml` — external SSD override

Add to the **B2B data paths** block (~line 71):

```yaml
    hedgedoc_data_dir: "{{ external_storage_root }}/hedgedoc/uploads"
```

Ensures `blank=true` reset wipes the right directory when external storage is active.

## 14. `tasks/nginx.yml` — auto-enable vhost

Add to the default `nginx_sites_enabled` list build (~line 130, next to outline.conf):

```yaml
         + ((install_hedgedoc | default(false)) | ternary(['hedgedoc.conf'], []))
```

## 15. Nginx vhost (delivered)

File: `templates/nginx/sites-available/hedgedoc.conf` — already in this role's PR. Auto-activates when `install_hedgedoc=true`.

## 16. Smoke test

```bash
# One-shot enable + render + bring up
ansible-playbook main.yml -K -e install_hedgedoc=true --tags hedgedoc,b2b,stacks,postgresql

# Verify
docker ps | grep hedgedoc           # Up (healthy)
curl -k https://hedgedoc.dev.local  # 200 / login page
# Click "Sign in with Authentik" → Authentik consent → back at HedgeDoc logged in
```

### Failure modes
- **502 Bad Gateway**: container still starting — `docker logs b2b-hedgedoc-1 -f`, wait ~30s after first up.
- **OIDC "invalid redirect_uri"**: run Authentik post-start (`--tags authentik`) so the provider is (re)created with the configured redirect URI.
- **"Cannot connect to database"**: `install_postgresql` must be true and `hedgedoc` DB + user provisioned — re-run with `--tags postgresql`.
