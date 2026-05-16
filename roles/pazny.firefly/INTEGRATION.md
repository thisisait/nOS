# pazny.firefly — Integration points

Non-role files that must be edited to wire the role into the nOS playbook. Apply each patch below verbatim; the role is inert without them.

---

## 1) `default.config.yml` — install toggle (B2B section)

Add next to the other B2B toggles (around line 144–149):

```yaml
# ── B2B stack (CRM/ERP/helpdesk/chat/wiki) ──────────────────────────────────
install_erpnext: false
install_freescout: true
install_outline: true
install_firefly: false          # Firefly III - personal finance manager    [requires: MariaDB, Redis Docker]
```

---

## 2) `default.config.yml` — Firefly service block

Append a service block (after the Outline section, before `# -- AI orchestration --`):

```yaml
# ==============================================================================
# FIREFLY III - Personal Finance Manager (b2b stack)
# SSO: Authentik proxy outpost (remote_user_guard -> REMOTE_USER header)
# Requires: MariaDB + Redis Docker
# ==============================================================================

firefly_version: "version-6.2.21"
firefly_domain: "firefly.{{ instance_tld | default('dev.local') }}"
firefly_port: 3014
firefly_upload_dir: "{{ ansible_facts['env']['HOME'] }}/firefly/upload"
firefly_export_dir: "{{ ansible_facts['env']['HOME'] }}/firefly/export"
firefly_db_name: "firefly"
firefly_db_user: "firefly"
firefly_tz: "Europe/Prague"
firefly_default_language: "en_US"
```

---

## 3) `default.config.yml` — MariaDB database + user

Extend `mariadb_databases` (around line 705) and `mariadb_users` (around line 712):

```yaml
mariadb_databases:
  - name: "wordpress"
  - name: "nextcloud"
  - name: "freescout"
  - name: "erpnext"
  - name: "asterisk"
  - name: "firefly"                      # << NEW

mariadb_users:
  # ... existing entries ...
  - name: "firefly"                      # << NEW
    password: "{{ firefly_db_password | default(global_password_prefix + '_pw_firefly') }}"
    priv: "firefly.*:ALL"
```

---

## 4) `default.config.yml` — `authentik_oidc_apps` entry (proxy type)

Append under the "Proxy-auth services" section of `authentik_oidc_apps` (around line 1523+):

```yaml
  - name: "Firefly III"
    slug: "firefly"
    enabled: "{{ install_firefly | default(false) }}"
    launch_url: "https://{{ firefly_domain | default('firefly.dev.local') }}"
    external_host: "https://{{ firefly_domain | default('firefly.dev.local') }}"
    type: "proxy"
```

**Why proxy (not native OIDC):** Firefly III's native auth integrations require running Laravel Passport as its own OAuth2 *server* or configuring a fully custom OIDC guard — both fragile across upgrades. The supported reverse-proxy pattern (`AUTHENTICATION_GUARD=remote_user_guard`) drops the whole OIDC dance onto the Authentik proxy outpost, which is already wired for every other proxy-auth service in nOS.

---

## 5) `default.config.yml` — `authentik_app_tiers`

Add to the `authentik_app_tiers:` map (around line 1425):

```yaml
authentik_app_tiers:
  # ... existing entries ...
  firefly: 2        # finance = manager tier (Tier 2, sensitive)
```

---

## 6) `default.credentials.yml` — secrets

Append after the OUTLINE block (around line 212):

```yaml
# ==============================================================================
# FIREFLY III (only when install_firefly: true)
# Login: via Authentik proxy outpost (remote_user_guard) - no local password
# Requires: MariaDB + Redis Docker
# ==============================================================================

firefly_db_password: "{{ global_password_prefix }}_pw_firefly"
firefly_app_key: "base64:{{ global_password_prefix }}_pw_firefly_app_key_PLACEHOLDER_32B"
# firefly_app_key is the Laravel APP_KEY. When blank=true, main.yml auto-generates
# it via `openssl rand -base64 32` with a `base64:` prefix. Changing it invalidates on-disk data.
```

---

## 7) `main.yml` — auto-generate `firefly_app_key` (DESTRUCTIVE group)

Firefly III's `APP_KEY` encrypts persistent user data (OAuth2 client secrets, 2FA tokens, reminder-channel credentials). Rotating it breaks existing DB rows — must live in the **destructive** group (blank=true / destroy_state=true only), same as `outline_secret_key`.

Extend the existing block around line 382–388:

```yaml
- name: "Regenerate DESTRUCTIVE stateless secrets (blank or destroy_state)"
  ansible.builtin.set_fact:
    infisical_encryption_key: "{{ lookup('pipe', 'openssl rand -hex 16') }}"
    infisical_auth_secret: "{{ lookup('pipe', 'openssl rand -base64 32') }}"
    outline_secret_key: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
    bluesky_pds_rotation_key: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
    firefly_app_key: "base64:{{ lookup('pipe', 'openssl rand -base64 32') }}"   # << NEW
  when: (blank | default(false) | bool) or (destroy_state | default(false) | bool)
  tags: ['always']
```

Also update the warning message list on line 394:

```yaml
msg: |
  WARNING: infisical_encryption_key, outline_secret_key, bluesky_pds_rotation_key,
  firefly_app_key preserved from the previous run (they have no lazy regeneration on non-blank runs).
```

---

## 8) `main.yml` — auto-enable Redis Docker (around line 352–362)

Extend the `Auto-enable Redis Docker for services that require it` condition:

```yaml
when: >
  (install_authentik | default(false)) or
  (install_infisical | default(false)) or
  (install_erpnext | default(false)) or
  (install_outline | default(false)) or
  (install_superset | default(false)) or
  (install_firefly | default(false))            # << NEW
```

(No change needed for MariaDB — Firefly uses the same shared `install_mariadb` path as WordPress/Nextcloud/FreeScout.)

---

## 9) `tasks/stacks/stack-up.yml` — compose template + role render + stack list

### 9a) b2b compose template gate (around line 35–40):

```yaml
- name: "[Stacks] Deploy b2b compose"
  ansible.builtin.template:
    src: "stacks/b2b/docker-compose.yml.j2"
    dest: "{{ stacks_dir }}/b2b/docker-compose.yml"
    mode: '0644'
  when: >
    install_erpnext | default(false) or
    install_freescout | default(false) or
    install_outline | default(false) or
    install_firefly | default(false)            # << NEW
```

### 9b) B2B role render (around line 88–91, append):

```yaml
# B2B roles
- { name: "[Stacks] pazny.erpnext render",   ansible.builtin.include_role: { name: pazny.erpnext,   apply: { tags: ['erpnext']   } }, when: "install_erpnext | default(false)",   tags: ['erpnext']   }
- { name: "[Stacks] pazny.freescout render", ansible.builtin.include_role: { name: pazny.freescout, apply: { tags: ['freescout'] } }, when: "install_freescout | default(false)", tags: ['freescout'] }
- { name: "[Stacks] pazny.outline render",   ansible.builtin.include_role: { name: pazny.outline,   apply: { tags: ['outline']   } }, when: "install_outline | default(false)",   tags: ['outline']   }
- { name: "[Stacks] pazny.firefly render",   ansible.builtin.include_role: { name: pazny.firefly,   apply: { tags: ['firefly']   } }, when: "install_firefly | default(false)",   tags: ['firefly']   }   # << NEW
```

### 9c) `_remaining_stacks` condition (around line 109):

```yaml
((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_firefly | default(false)) | ternary(['b2b'], []))
```

### 9d) No post-start role needed — Firefly auto-provisions users on first `REMOTE_USER` hit; schema migrates automatically at container start.

---

## 10) `templates/stacks/b2b/docker-compose.yml.j2` — no change required

The base b2b compose template declares only `services: {}` + networks; the `firefly` service is rendered per-role into `{{ stacks_dir }}/b2b/overrides/firefly.yml` and picked up by the `find`/`-f` merge loop in `stack-up.yml`.

---

## 11) Smoke test

```bash
# Enable, run, verify
ansible-playbook main.yml -K -e install_firefly=true -e install_authentik=true

# DNS
grep -q "firefly.dev.local" /etc/hosts || echo "127.0.0.1 firefly.dev.local" | sudo tee -a /etc/hosts

# HTTP: expect 302 to /outpost.goauthentik.io/... when not authenticated
curl -sSI -o /dev/null -w "%{http_code} %{redirect_url}\n" -k https://firefly.dev.local/

# Container health
docker compose -p b2b ps firefly
docker compose -p b2b logs firefly | tail -40

# DB bootstrap (idempotent)
docker compose -p infra exec -T mariadb \
  mariadb -uroot -p"{{ mariadb_root_password }}" -e "SHOW DATABASES LIKE 'firefly';"

# End-to-end: login in browser at https://firefly.dev.local -> Authentik -> Firefly
# first request after SSO should create a local account keyed on REMOTE_EMAIL
```

---

## 12) Rollback

```bash
# From INTEGRATION.md standpoint — set install_firefly: false and re-run,
# or nuke state manually:
docker compose -p b2b stop firefly && docker compose -p b2b rm -f firefly
rm -rf ~/firefly/
# Drop DB only if you really want to lose it:
docker compose -p infra exec -T mariadb \
  mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "DROP DATABASE firefly; DROP USER 'firefly'@'%';"
```
