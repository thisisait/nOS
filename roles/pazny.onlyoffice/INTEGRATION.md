# INTEGRATION: pazny.onlyoffice

This document describes every change outside `roles/pazny.onlyoffice/` that the
parent agent (orchestrator) applies mechanically when merging this role.

## 1. `default.config.yml` — install toggle

Insert into the `# ── B2B stack (CRM/ERP/helpdesk/chat/wiki) ──` block
(around lines 145–148), after the `install_outline: ...` line:

```yaml
install_onlyoffice: false        # ONLYOFFICE Document Server – collaborative docs backend [Docker, JWT]
```

## 2. `default.config.yml` — `authentik_oidc_apps` entry (proxy auth)

Append to the `authentik_oidc_apps:` list (around line 1566, before the helper
vars block near line 1610). ONLYOFFICE is a **backend service** — proxy auth
protects the UI only; API endpoints are unauthenticated at the Authentik layer
(JWT validation happens on the ONLYOFFICE side).

```yaml
  - name: "ONLYOFFICE"
    slug: "onlyoffice"
    enabled: "{{ install_onlyoffice | default(false) }}"
    launch_url: "https://{{ onlyoffice_domain | default('office.dev.local') }}"
    external_host: "https://{{ onlyoffice_domain | default('office.dev.local') }}"
    type: "proxy"
```

## 3. `default.config.yml` — helper vars

Not needed (proxy auth → no OIDC `client_id` / `client_secret`).

## 4. `default.config.yml` — `authentik_app_tiers` entry

Insert into the `authentik_app_tiers:` map (around lines 1425–1448):

```yaml
  onlyoffice: 3
```

## 5. `default.credentials.yml` — new secrets

Insert:

```yaml
onlyoffice_jwt_secret: "{{ global_password_prefix }}_pw_onlyoffice_jwt"
```

The value is a fallback for non-blank runs. On `blank=true` the secret is
overwritten by the auto-generated value in `main.yml` (see section 6).

## 6. `main.yml` — auto-generated secret block

Insert into the "Auto-regenerate stateless secrets (every run — safe group)"
block in `main.yml` (around lines 372–380):

```yaml
        onlyoffice_jwt_secret: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
```

Note: `onlyoffice_jwt_secret` is **stateless** — the JWT is only used for API
signing, not for encrypting persistent data. The safe group is the correct
choice (the secret is regenerated every run and synchronized with the host
applications via Ansible templates).
**If the secret is shared with an external application** that is not tracked by
the Ansible playbook (for example Nextcloud with manual configuration),
consider moving it to the destructive group and synchronizing it manually.

## 7. `tasks/stacks/stack-up.yml` — role include

Insert into the `# B2B roles` block (around lines 88–91), after the
`pazny.outline render` line:

```yaml
- { name: "[Stacks] pazny.onlyoffice render", ansible.builtin.include_role: { name: pazny.onlyoffice, apply: { tags: ['onlyoffice'] } }, when: "install_onlyoffice | default(false)", tags: ['onlyoffice'] }
```

## 8. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update

Update the expression that detects the b2b stack (around line 109):

**Before:**
```yaml
((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false)) | ternary(['b2b'], []))
```

**After:**
```yaml
((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_onlyoffice | default(false)) | ternary(['b2b'], []))
```

## 9. `tasks/stacks/stack-up.yml` — post.yml include

Not needed — the role does not have a `tasks/post.yml`.

## 10. Database provisioning

Not needed — ONLYOFFICE CE uses an **embedded postgres** inside the container
(bind mount `{{ onlyoffice_db_dir }}:/var/lib/postgresql`). No writes into the
core-up.yml postgres/mariadb blocks.

## 11. Nginx vhost

Path: `templates/nginx/sites-available/onlyoffice.conf`

Activated automatically via the `install_onlyoffice` flag (the existing
auto-enable pattern in `tasks/nginx/`). No entry in `nginx_sites_enabled` is
required.

### Architecture of the location blocks (IMPORTANT)

The vhost has **two location blocks** with distinct authorization policies:

- **`location /`** (UI paths: `/welcome`, admin panel, static web assets)
  - **Authentik forward_auth = ON** (protects the UI against public access)
  - WebSocket upgrade headers (real-time collaboration)
  - Large buffers (`client_max_body_size 100m`, `proxy_buffer_size 32k`)

- **`location ~ ^/(healthcheck|ConvertService\.ashx|coauthoring|OfficeWeb|cache|info|[0-9.]+/).*$`** (API + embed + versioned assets)
  - **Authentik forward_auth = OFF** (host applications call it with a JWT token)
  - Same buffers and WebSocket headers as `/`
  - ONLYOFFICE validates the JWT signature on its side → security preserved

Without this split the Nextcloud iframe could not call
`https://office.dev.local/ConvertService.ashx` (it would be blocked by
Authentik even with a valid JWT).

## 12. Smoke test

After `ansible-playbook main.yml -K -e install_onlyoffice=true --tags onlyoffice`:

```bash
# Container running
docker ps | grep onlyoffice

# UI is behind Authentik (302 -> auth.dev.local)
curl -sk -o /dev/null -w "%{http_code}\n" https://office.dev.local/
# expected: 302

# API endpoint IS reachable (proxy passthrough, JWT validation on ONLYOFFICE)
curl -sk https://office.dev.local/healthcheck
# expected: "true"

# Conversion endpoint (no JWT -> 403 from ONLYOFFICE, but nginx lets it through)
curl -sk -o /dev/null -w "%{http_code}\n" https://office.dev.local/ConvertService.ashx
# expected: 403 or 200 (NOT 302 to Authentik!)
```

## 13. Integration addendum — wiring up host applications

For **Nextcloud** integration:
1. Nextcloud UI → Apps → install `ONLYOFFICE` (official connector).
2. Settings → ONLYOFFICE:
   - **Document Editing Service URL**: `https://office.dev.local/`
   - **Secret key (JWT)**: the value of `onlyoffice_jwt_secret` from `credentials.yml`
   - **JWT Header**: `Authorization` (default)

For **BookStack**: ONLYOFFICE module → the same two values.

For **Outline**: there is no official ONLYOFFICE plugin; Outline uses its own
ProseMirror editor. ONLYOFFICE in nOS is primarily a fit for
Nextcloud-based document workflows.
