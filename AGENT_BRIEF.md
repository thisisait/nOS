# AGENT BRIEF — pazny.* Docker role authoring

This document is a **binding specification standard** for all agents authoring new Ansible roles for nOS Docker services. Read carefully — the project has strong conventions.

## 1. Project context

- **nOS** = Ansible playbook for macOS Apple Silicon with ~46 Docker services (plus ~13 non-Docker host roles — 59 roles total under the `pazny.*` namespace) organized into 8 compose stacks (`infra`, `observability`, `iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`).
- Each Docker service has **its own Ansible role** under the `pazny.*` namespace that renders a **compose override fragment** into `{{ stacks_dir }}/<stack>/overrides/<service>.yml`. The orchestrator (`tasks/stacks/stack-up.yml` or `core-up.yml`) collects overrides via `ansible.builtin.find` and passes them as `-f` flags to `docker compose up`.
- **Glasswing** (`files/project-glasswing/`) = Nette PHP control plane dashboard with a unified `systems` table (SQLite). Each service = record in `systems` with parent_id hierarchy (stack → service → sub-service), health tracking, scan state, versions. The `pazny.glasswing` Ansible role imports `service-registry.json` into the DB on deploy.
- Root worktree path = `/Users/pazny/projects/nOS/.claude/worktrees/<your-name>` (branch based on `master`). The old `mac-dev-playbook/` path was retired as part of the nOS rebrand.

## 2. Git workflow (REQUIRED)

- Primary branch = **`master`**. The `dev` branch does not exist (removed 2026-04-16).
- If you work in a worktree, your branch starts from `master`. If you work directly, commit on `master`.
- Each commit = Conventional Commits (`feat:`, `fix:`, `chore:`), **no Co-Authored-By, no `--author` flag**. Commit message in English, imperative.
- At the end of work do atomic commits. **DO NOT MERGE or push** unless you are the main orchestrator.

## 3. Required role structure

```
roles/pazny.<service>/
├── defaults/main.yml      # all variables with defaults
├── tasks/main.yml         # data dir + compose override render
├── tasks/post.yml         # (opt.) post-start API/DB setup
├── templates/compose.yml.j2
├── handlers/main.yml      # restart handler
├── meta/main.yml          # galaxy metadata
└── README.md              # 2–10 lines: what the role does, dependencies
```

### 3.1 `defaults/main.yml` — conventions

```yaml
---
# ==============================================================================
# pazny.<service> — <one-line description> (<stack> compose stack)
#
# Credentials (<service>_db_password, <service>_secret_key, ...) remain
# in default.credentials.yml — centralized for prefix rotation.
# ==============================================================================

<service>_version: "<pinned-stable-tag>"        # see version_policy (never "latest" without fallback)
<service>_domain: "<subdomain>.{{ instance_tld | default('dev.local') }}"
<service>_port: <unique-port-3xxx>              # host port (see PORT REGISTRY)
<service>_data_dir: "{{ ansible_facts['env']['HOME'] }}/<service>/data"
<service>_db_name: "<service>"                  # if it has a DB
<service>_db_user: "<service>"
<service>_mem_limit: "{{ docker_mem_limit_standard | default('1g') }}"
<service>_cpus: "{{ docker_cpus_standard | default('1.0') }}"
# For `blank=true` wipe during the reset phase (tasks/reset/):
<service>_external_data_dir_override: ""        # opt. alias for /Volumes/SSD1TB/<service>
```

**Version pinning**: Find the current stable image tag (e.g. `docker inspect` or Docker Hub). Use a **specific CVE-patched tag**, never `latest`. Example: `linuxserver/code-server:4.105.1-ls290` instead of `latest`.

### 3.2 `tasks/main.yml` — conventions

```yaml
---
# ==============================================================================
# pazny.<service>/tasks/main.yml
#
# Called from tasks/stacks/stack-up.yml BEFORE `docker compose up <stack>`:
# creates the data dir, renders the compose override fragment.
# ==============================================================================

- name: "[pazny.<service>] Ensure data directory exists"
  ansible.builtin.file:
    path: "{{ <service>_data_dir }}"
    state: directory
    mode: '0755'

- name: "[pazny.<service>] Render compose override fragment"
  ansible.builtin.template:
    src: compose.yml.j2
    dest: "{{ stacks_dir }}/<stack>/overrides/<service>.yml"
    mode: '0644'
  notify: Restart <service>
```

### 3.3 `templates/compose.yml.j2` — conventions

**NEVER** declare top-level `networks:` or `volumes:` — they are in the stack's base compose template. Declare only `services:`.

```jinja
# =============================================================================
# pazny.<service> — compose override fragment
# Merged into `docker compose up` via ansible.builtin.find over
# {{ stacks_dir }}/<stack>/overrides/*.yml.
# =============================================================================

services:
  <service>:
    image: <registry>/<image>:{{ <service>_version | default('<pinned>') }}
    restart: unless-stopped
    ports:
{% if services_lan_access | default(false) %}
      - "{{ <service>_port }}:<container-port>"
{% else %}
      - "127.0.0.1:{{ <service>_port }}:<container-port>"
{% endif %}
    volumes:
      - {{ <service>_data_dir }}:<container-path>
{% if install_authentik | default(false) %}
      - {{ stacks_dir }}/shared-certs/rootCA.pem:/usr/local/share/ca-certificates/mkcert-ca.crt:ro
{% endif %}
    environment:
      # service-specific env vars here
{% if install_authentik | default(false) %}
      # ── Authentik SSO (OIDC) ───────────────────────────────────────────────
      OIDC_CLIENT_ID: "{{ authentik_oidc_<service>_client_id }}"
      OIDC_CLIENT_SECRET: "{{ authentik_oidc_<service>_client_secret }}"
      # ... (depends on the specific app, see section 4)
{% endif %}
{% if install_authentik | default(false) %}
    extra_hosts:
      - "{{ authentik_domain | default('auth.dev.local') }}:host-gateway"
{% endif %}
    networks:
      - <stack>_net
      - {{ stacks_shared_network }}
    logging:
      driver: "json-file"
      options:
        max-size: "20m"
        max-file: "5"
    mem_limit: {{ <service>_mem_limit | default(docker_mem_limit_standard) }}
    cpus: {{ <service>_cpus | default(docker_cpus_standard | default('1.0')) }}
```

**Important**:
- `<stack>_net` = internal network name (e.g. `iiab_net`, `b2b_net`, `devops_net`).
- `stacks_shared_network` = shared network (enables cross-stack communication with the infra stack — Postgres, Redis, Authentik).
- If connecting to Postgres / MariaDB / Redis from the infra stack, `DATABASE_URL` = `postgres://user:pass@postgresql:5432/db` (container name = network alias).

### 3.4 `handlers/main.yml`

```yaml
---
- name: Restart <service>
  ansible.builtin.shell: >
    {{ docker_bin }} compose -f "{{ stacks_dir }}/<stack>/docker-compose.yml" -p <stack>
    restart <service>
  failed_when: false
```

### 3.5 `meta/main.yml`

```yaml
---
galaxy_info:
  role_name: <service>
  namespace: pazny
  author: Pázny
  description: <service short description> in Docker compose override (nOS <stack> stack)
  license: MIT
  min_ansible_version: "2.14"
  platforms:
    - name: MacOSX
      versions:
        - all
dependencies: []
collections: []
```

## 4. SSO patterns

### 4.1 Native OIDC (preferred, if the service supports it)

1. Add OIDC env vars to the compose template under `{% if install_authentik %}`.
2. Write in INTEGRATION.md:
   - entry into `authentik_oidc_apps` in `default.config.yml`:
     ```yaml
     - name: "<ServiceName>"
       slug: "<service>"
       enabled: "{{ install_<service> | default(false) }}"
       client_id: "nos-<service>"
       client_secret: "{{ global_password_prefix }}_pw_oidc_<service>"
       redirect_uris: "https://{{ <service>_domain | default('<sub>.dev.local') }}/<oidc-callback-path>"
       launch_url: "https://{{ <service>_domain | default('<sub>.dev.local') }}"
     ```
   - helper vars (near the end of `default.config.yml`):
     ```yaml
     authentik_oidc_<service>_client_id: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', '<service>') | first).client_id }}"
     authentik_oidc_<service>_client_secret: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', '<service>') | first).client_secret }}"
     ```
   - entry into `authentik_app_tiers` (tier 1 admin / 2 manager / 3 user / 4 guest).

### 4.2 Proxy auth (fallback if the service does not support OIDC)

- In the nginx vhost add `include /etc/nginx/authentik-forward-auth.conf;` at vhost level (existing pattern — see e.g. `templates/nginx/sites-available/uptime-kuma.conf`).
- Add entry to `authentik_oidc_apps` with `type: "proxy"` + `external_host` (without `client_id` / `redirect_uris`).

Reference role for native OIDC: **`pazny.outline`** (Postgres + OIDC).
Reference role for proxy: **`pazny.uptime_kuma`**.

## 5. Nginx vhost (if the service has a web UI)

Create `templates/nginx/sites-available/<service>.conf` — copy the structure of the closest similar vhost:
- **Ports on 127.0.0.1 only** (container binds on `127.0.0.1:<port>`, nginx proxy_pass to localhost).
- `listen 80` + `listen 443 ssl` + HTTP→HTTPS redirect.
- `ssl_certificate /opt/homebrew/etc/mkcert/<domain>.pem` (mkcert auto-generates).
- `proxy_set_header Host $host; X-Forwarded-For ...; X-Real-IP ...; X-Forwarded-Proto ...`.
- For proxy-auth services: `include` the Authentik forward auth snippet.

The vhost itself activates automatically via `tasks/nginx/` if the name = `<service_slug>.conf` and the name matches the `install_<service>` flag (see existing pattern).

## 6. Port Registry (avoid conflicts!)

Check `grep -r "^<service>_port:" roles/` and `grep "ports:" templates/stacks/` for collisions. Use a **unique port 3xxx–9xxx** outside of:
- 80/443 (nginx), 5432 (postgres), 3306 (mariadb), 6379 (redis), 3000 (grafana), 9000 (portainer), 9090 (prometheus), 3100 (loki), 3200 (tempo), 8070 (jsos), 8099 (bone)
- Taken: 3001 (gitea), 3005 (outline), 3006 (n8n), 3007 (paperclip), 3008 (freescout), 8000 (various), 8080/81/82, 8181 (calibre), 8123 (homeassistant), 9443 (portainer-ssl)

## 7. Post-start setup (optional — only if the service requires API/DB init)

If the service needs something like: creating an admin user, importing dashboards, DB migrations, etc. — make `tasks/post.yml`. It is called AFTER `docker compose up` from `stack-up.yml`. Examples: `roles/pazny.nextcloud/tasks/post.yml`, `roles/pazny.gitea/tasks/post.yml`. Otherwise you **do not need** `post.yml`.

## 8. Deliverables — what you MUST create

### In role dir `roles/pazny.<service>/`:
- [ ] `defaults/main.yml`
- [ ] `tasks/main.yml`
- [ ] `templates/compose.yml.j2`
- [ ] `handlers/main.yml`
- [ ] `meta/main.yml`
- [ ] `README.md` (brief)
- [ ] (opt.) `tasks/post.yml`
- [ ] **`INTEGRATION.md`** — MUST exist! See section 9.

### Outside the role dir:
- [ ] `templates/nginx/sites-available/<service>.conf` (if web UI)

### DO NOT touch (the parent agent will handle these after merge):
- NO `default.config.yml` — only write a patch into INTEGRATION.md
- NO `default.credentials.yml` — only a patch into INTEGRATION.md
- NO `tasks/stacks/stack-up.yml` / `core-up.yml` — patch into INTEGRATION.md
- NO `tasks/reset/*.yml` — patch into INTEGRATION.md if the service has an external data path
- NO `templates/stacks/<stack>/docker-compose.yml.j2` — only if the stack is **new** (see section 10)

## 9. `INTEGRATION.md` — exact format (the parent agent applies this mechanically)

Create `roles/pazny.<service>/INTEGRATION.md`:

```markdown
# INTEGRATION: pazny.<service>

## 1. `default.config.yml` — install toggle
Insert after `install_<similar>: <bool>` line (~line 150):
​```yaml
install_<service>: false              # <one-line description> [Docker, requires: ...]
​```

## 2. `default.config.yml` — authentik_oidc_apps entry
Append to `authentik_oidc_apps:` list (before helper vars block):
​```yaml
  - name: "<ServiceName>"
    slug: "<service>"
    enabled: "{{ install_<service> | default(false) }}"
    client_id: "nos-<service>"
    client_secret: "{{ global_password_prefix }}_pw_oidc_<service>"
    redirect_uris: "https://{{ <service>_domain | default('<sub>.dev.local') }}/<callback-path>"
    launch_url: "https://{{ <service>_domain | default('<sub>.dev.local') }}"
​```
(Or a `type: "proxy"` entry for proxy-auth services.)

## 3. `default.config.yml` — helper vars (only if native OIDC)
Insert near other `authentik_oidc_*_client_id` vars:
​```yaml
authentik_oidc_<service>_client_id: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', '<service>') | first).client_id }}"
authentik_oidc_<service>_client_secret: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', '<service>') | first).client_secret }}"
​```

## 4. `default.config.yml` — authentik_app_tiers entry
Add to `authentik_app_tiers:`:
​```yaml
<service>: <1|2|3|4>
​```

## 5. `default.credentials.yml` — if the role introduces new secrets
(DB password, session secret, API keys — if present in the role's compose template)
​```yaml
<service>_db_password: "{{ global_password_prefix }}_pw_<service>"
<service>_secret_key: "{{ global_password_prefix }}_pw_<service>_secret"
​```

## 6. `tasks/stacks/stack-up.yml` — role include
Insert into the appropriate "# <Stack> roles" block:
​```yaml
- { name: "[Stacks] pazny.<service> render", ansible.builtin.include_role: { name: pazny.<service>, apply: { tags: ['<service>'] } }, when: "install_<service> | default(false)", tags: ['<service>'] }
​```

## 7. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update (if adding a stack to the active list)
(Edit only if the service is in an EXISTING stack that is not always active. If your stack is already `iiab` or a similar "always active" stack, skip.)

## 8. `tasks/stacks/stack-up.yml` — post.yml include (only if the role has `post.yml`)
​```yaml
- { name: "[Stacks] pazny.<service> post", ansible.builtin.include_role: { name: pazny.<service>, tasks_from: post.yml, apply: { tags: ['<service>'] } }, when: "install_<service> | default(false)", tags: ['<service>'] }
​```

## 9. Database provisioning (if the service uses a DB)
### Postgres
Insert into the `tasks/stacks/core-up.yml` postgres provision block:
​```yaml
- { name: "<service> DB", db: "<service>", owner: "<service>", password: "{{ <service>_db_password }}" }
​```
### MariaDB
Same pattern for the MariaDB block.

## 10. Nginx vhost (documentation)
State the exact path + that it activates automatically via the `install_<service>` flag.

## 11. Smoke test
After `ansible-playbook main.yml -K -e install_<service>=true --tags <service>` verify:
- `docker ps | grep <service>`  → Up
- `curl -k https://<service>.dev.local` → 200
- Authentik login redirect (if OIDC)
```

## 10. New stack (only for agents creating one)

If your role creates a new stack (e.g. `mail`, `health`, `engineering` — the parent will tell you explicitly in the prompt), you MUST CREATE:
- `templates/stacks/<stack>/docker-compose.yml.j2` — base with `services: {}` + `networks: { <stack>_net: driver: bridge }`
- In INTEGRATION.md section 7 describe the change to `_remaining_stacks` + the addition of a `tasks/stacks/stack-up.yml` deploy block.

## 11. Quality — what the parent will check

- `python3 -c "import yaml; yaml.safe_load(open('roles/pazny.<service>/defaults/main.yml'))"` → OK
- `python3 -c "import yaml; yaml.safe_load(open('roles/pazny.<service>/tasks/main.yml'))"` → OK
- `python3 -c "import yaml; yaml.safe_load(open('roles/pazny.<service>/meta/main.yml'))"` → OK
- Compose template is valid Jinja2 + valid docker-compose YAML after render
- Port is unique (project grep)
- All secrets go through the `{{ global_password_prefix }}_pw_*` pattern
- No hardcoded `dev.local` — always `{{ instance_tld | default('dev.local') }}`
- INTEGRATION.md is complete and precise
- Clean commit on your branch, no unrelated files

## 12. Glasswing System Entity (new system → registration)

Every service automatically appears in the Glasswing Hub dashboard thanks to the pipeline:

1. **Ansible service-registry.json.j2** — the role adds an entry to `templates/service-registry.json.j2` (under the Wave A+B block):
   ```jinja
   {% if install_<service> | default(false) %}
   {% set _ = _services.append({
     "name": "<ServiceName>",
     "category": "<category>",
     "tier": 1,
     "enabled": true,
     "toggle_var": "install_<service>",
     "domain": <service>_domain | default('<sub>.dev.local'),
     "port": <service>_port | default(<port>),
     "url": "https://" ~ (<service>_domain | default('<sub>.dev.local')),
     "type": "docker",
     "stack": "<stack>",
     "version": <service>_version | default('<pinned>'),
     "description": "<short description>"
   }) %}
   {% endif %}
   ```

2. **Glasswing ingest** — `bin/ingest-registry.php` (called by the `pazny.glasswing` Ansible role) imports the JSON into the SQLite `systems` table:
   - `id` = toggle_var (e.g. `install_nextcloud`)
   - `parent_id` = `stack-<stack>` (created automatically)
   - Health probing, scan state, version tracking — all in the DB

3. **Systems table schema** (key columns):
   ```
   id, parent_id, name, description, type, category, stack, version,
   domain, port, url, toggle_var, enabled, health_status, health_http_code,
   health_ms, health_checked_at, priority, upstream_repo, source
   ```

4. **API** — `GET /api/v1/hub/systems` (flat list + stats), `?tree=1` (hierarchy), `/health` (live probes)

**Note**: In INTEGRATION.md section 10 add a patch for `service-registry.json.j2`.

## 13. Agent workflow summary

1. Read this brief and YOUR service-specific prompt (from the parent agent).
2. Read 1–2 reference existing roles (the parent will name them).
3. Create all deliverables per section 8.
4. Add an entry to `service-registry.json.j2` (section 12).
5. Validate YAML + check ports.
6. Commit on your branch (Conventional Commits, no Co-Authored-By).
7. Return a brief report to the parent: what you did, branch name, any risks/uncertainties.
