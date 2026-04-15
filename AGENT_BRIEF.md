# AGENT BRIEF — pazny.* Docker role authoring

Tento dokument je **závazný specifikační standard** pro všechny agenty píšící nové Ansible role pro devBoxNOS Docker služby. Čti pozorně, projekt má silné konvence.

## 1. Kontext projektu

- **devBoxNOS** = Ansible playbook pro macOS Apple Silicon s 45+ Docker službami organizovanými do 8 compose stacků (`infra`, `observability`, `iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`).
- Každá Docker služba má **vlastní Ansible roli** pod namespace `pazny.*`, která renderuje **compose override fragment** do `{{ stacks_dir }}/<stack>/overrides/<service>.yml`. Orchestrátor (`tasks/stacks/stack-up.yml` nebo `core-up.yml`) sbírá overrides přes `ansible.builtin.find` a předává je jako `-f` flagy do `docker compose up`.
- Root worktree path = `/Users/pazny/projects/mac-dev-playbook/.claude/worktrees/<tvoje-jmeno>` (máš v HEAD branch based on `cc/hungry-banach` which je založen na `dev`).

## 2. Git workflow (POVINNÉ)

- Pracuj pouze ve svém worktree. **NE** commituj na `master`.
- Každý commit = Conventional Commits (`feat:`, `fix:`, `chore:`), **bez Co-Authored-By, bez `--author` flagu**. Commit message anglicky, imperativně.
- Na konci práce udělej jediný nebo několik atomických commitů na své větvi.
- **NEMERGUJ ani nepushuj**. Parent agent (orchestrator) to udělá.

## 3. Závazná struktura role

```
roles/pazny.<service>/
├── defaults/main.yml      # všechny proměnné s defaulty
├── tasks/main.yml         # data dir + compose override render
├── tasks/post.yml         # (opt.) post-start API/DB setup
├── templates/compose.yml.j2
├── handlers/main.yml      # restart handler
├── meta/main.yml          # galaxy metadata
└── README.md              # 2–10 řádků: co role dělá, závislosti
```

### 3.1 `defaults/main.yml` — konvence

```yaml
---
# ==============================================================================
# pazny.<service> — <one-line popis> (<stack> compose stack)
#
# Credentials (<service>_db_password, <service>_secret_key, ...) zustavaji
# v default.credentials.yml — centralizovane pro prefix rotation.
# ==============================================================================

<service>_version: "<pinned-stable-tag>"        # viz version_policy (nikdy "latest" bez fallback)
<service>_domain: "<subdomain>.{{ instance_tld | default('dev.local') }}"
<service>_port: <unique-port-3xxx>              # hostový port (viz PORT REGISTRY)
<service>_data_dir: "{{ ansible_facts['env']['HOME'] }}/<service>/data"
<service>_db_name: "<service>"                  # pokud má DB
<service>_db_user: "<service>"
<service>_mem_limit: "{{ docker_mem_limit_standard | default('1g') }}"
<service>_cpus: "{{ docker_cpus_standard | default('1.0') }}"
# Pro `blank=true` vymaže při reset-fázi (tasks/reset/):
<service>_external_data_dir_override: ""        # opt. alias pro /Volumes/SSD1TB/<service>
```

**Version pinning**: Najdi aktuální stable tag image (např. `docker inspect` nebo Docker Hub). Použij **konkrétní CVE-patched tag**, nikdy `latest`. Příklad: `linuxserver/code-server:4.105.1-ls290` místo `latest`.

### 3.2 `tasks/main.yml` — konvence

```yaml
---
# ==============================================================================
# pazny.<service>/tasks/main.yml
#
# Volano z tasks/stacks/stack-up.yml PRED `docker compose up <stack>`:
# vytvori data dir, vyrenderuje compose override fragment.
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

### 3.3 `templates/compose.yml.j2` — konvence

**NIKDY** nedeklaruj top-level `networks:` ani `volumes:` — jsou v base compose templateu stacku. Deklaruj jen `services:`.

```jinja
# =============================================================================
# pazny.<service> — compose override fragment
# Merged do `docker compose up` pres ansible.builtin.find nad
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
      # ... (podle konkrétní app, viz sekce 4)
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

**Důležité**:
- `<stack>_net` = jméno interní sítě (např. `iiab_net`, `b2b_net`, `devops_net`).
- `stacks_shared_network` = sdílená síť (umožňuje cross-stack komunikaci s infra stackem — Postgres, Redis, Authentik).
- Pokud připojuješ k Postgresu / MariaDB / Redis z infra stacku, `DATABASE_URL` = `postgres://user:pass@postgresql:5432/db` (jméno kontejneru = jméno sítě alias).

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
  description: <service short description> in Docker compose override (devBoxNOS <stack> stack)
  license: MIT
  min_ansible_version: "2.14"
  platforms:
    - name: MacOSX
      versions:
        - all
dependencies: []
collections: []
```

## 4. SSO patterny

### 4.1 Native OIDC (preferované, pokud service podporuje)

1. Do compose templateu přidej OIDC env vars pod `{% if install_authentik %}`.
2. Do INTEGRATION.md napiš:
   - entry do `authentik_oidc_apps` v `default.config.yml`:
     ```yaml
     - name: "<ServiceName>"
       slug: "<service>"
       enabled: "{{ install_<service> | default(false) }}"
       client_id: "devboxnos-<service>"
       client_secret: "{{ global_password_prefix }}_pw_oidc_<service>"
       redirect_uris: "https://{{ <service>_domain | default('<sub>.dev.local') }}/<oidc-callback-path>"
       launch_url: "https://{{ <service>_domain | default('<sub>.dev.local') }}"
     ```
   - helper vars (u konce `default.config.yml`):
     ```yaml
     authentik_oidc_<service>_client_id: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', '<service>') | first).client_id }}"
     authentik_oidc_<service>_client_secret: "{{ (authentik_oidc_apps | selectattr('slug', 'equalto', '<service>') | first).client_secret }}"
     ```
   - entry do `authentik_app_tiers` (tier 1 admin / 2 manager / 3 user / 4 guest).

### 4.2 Proxy auth (fallback pokud service OIDC nepodporuje)

- V nginx vhostu přidej `include /etc/nginx/authentik-forward-auth.conf;` na vhost level (existující pattern — viz např. `templates/nginx/sites-available/uptime-kuma.conf`).
- Do `authentik_oidc_apps` přidej entry s `type: "proxy"` + `external_host` (bez `client_id` / `redirect_uris`).

Referenční role pro OIDC native: **`pazny.outline`** (Postgres + OIDC).
Referenční role pro proxy: **`pazny.uptime_kuma`**.

## 5. Nginx vhost (pokud service má web UI)

Vytvoř `templates/nginx/sites-available/<service>.conf` — zkopíruj strukturu nejbližšího podobného vhostu:
- **Ports on 127.0.0.1 only** (container bindi na `127.0.0.1:<port>`, nginx proxy_pass na lokalhost).
- `listen 80` + `listen 443 ssl` + HTTP→HTTPS redirect.
- `ssl_certificate /opt/homebrew/etc/mkcert/<domain>.pem` (mkcert auto-vyrobí).
- `proxy_set_header Host $host; X-Forwarded-For ...; X-Real-IP ...; X-Forwarded-Proto ...`.
- Pro proxy-auth služby: `include` Authentik forward auth snippetu.

Vhost sám se aktivuje automaticky přes `tasks/nginx/` pokud jméno = `<service_slug>.conf` a jméno odpovídá `install_<service>` flagu (viz existing pattern).

## 6. Port Registry (vyhni se konfliktu!)

Zkontroluj `grep -r "^<service>_port:" roles/` a `grep "ports:" templates/stacks/` pro kolize. Použij **unikátní port 3xxx–9xxx** mimo:
- 80/443 (nginx), 5432 (postgres), 3306 (mariadb), 6379 (redis), 3000 (grafana), 9000 (portainer), 9090 (prometheus), 3100 (loki), 3200 (tempo), 8070 (jsos), 8099 (boxapi)
- Obsazené: 3001 (gitea), 3005 (outline), 3006 (n8n), 3007 (paperclip), 3008 (freescout), 8000 (various), 8080/81/82, 8181 (calibre), 8123 (homeassistant), 9443 (portainer-ssl)

## 7. Post-start setup (volitelné — jen pokud service vyžaduje API/DB init)

Pokud service potřebuje něco jako: vytvoření admin usera, import dashboardů, DB migrace, apod. — udělej `tasks/post.yml`. Volá se PO `docker compose up` z `stack-up.yml`. Příklady: `roles/pazny.nextcloud/tasks/post.yml`, `roles/pazny.gitea/tasks/post.yml`. Jinak `post.yml` **nepotřebuješ**.

## 8. Deliverables — co MUSÍŠ vytvořit

### V role dir `roles/pazny.<service>/`:
- [ ] `defaults/main.yml`
- [ ] `tasks/main.yml`
- [ ] `templates/compose.yml.j2`
- [ ] `handlers/main.yml`
- [ ] `meta/main.yml`
- [ ] `README.md` (stručný)
- [ ] (opt.) `tasks/post.yml`
- [ ] **`INTEGRATION.md`** — MUSÍ být! Viz sekce 9.

### Mimo role dir:
- [ ] `templates/nginx/sites-available/<service>.conf` (pokud web UI)

### NE-dotýkej se (parent agent to udělá po merge):
- ❌ `default.config.yml` — pouze napiš patch do INTEGRATION.md
- ❌ `default.credentials.yml` — jen patch do INTEGRATION.md
- ❌ `tasks/stacks/stack-up.yml` / `core-up.yml` — patch do INTEGRATION.md
- ❌ `tasks/reset/*.yml` — patch do INTEGRATION.md pokud služba má externí data path
- ❌ `templates/stacks/<stack>/docker-compose.yml.j2` — jen pokud je stack **nový** (viz sekce 10)

## 9. `INTEGRATION.md` — přesný formát (tohle parent agent mechanicky aplikuje)

Vytvoř `roles/pazny.<service>/INTEGRATION.md`:

```markdown
# INTEGRATION: pazny.<service>

## 1. `default.config.yml` — install toggle
Insert after `install_<similar>: <bool>` line (~řádek 150):
​```yaml
install_<service>: false              # <one-line popis> [Docker, vyžaduje: ...]
​```

## 2. `default.config.yml` — authentik_oidc_apps entry
Append to `authentik_oidc_apps:` list (before helper vars block):
​```yaml
  - name: "<ServiceName>"
    slug: "<service>"
    enabled: "{{ install_<service> | default(false) }}"
    client_id: "devboxnos-<service>"
    client_secret: "{{ global_password_prefix }}_pw_oidc_<service>"
    redirect_uris: "https://{{ <service>_domain | default('<sub>.dev.local') }}/<callback-path>"
    launch_url: "https://{{ <service>_domain | default('<sub>.dev.local') }}"
​```
(Nebo `type: "proxy"` entry pro proxy-auth služby.)

## 3. `default.config.yml` — helper vars (jen pokud OIDC native)
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

## 5. `default.credentials.yml` — pokud role zavádí nové secrets
(DB password, session secret, API keys — pokud je v role compose template)
​```yaml
<service>_db_password: "{{ global_password_prefix }}_pw_<service>"
<service>_secret_key: "{{ global_password_prefix }}_pw_<service>_secret"
​```

## 6. `tasks/stacks/stack-up.yml` — role include
Insert into appropriate "# <Stack> roles" block:
​```yaml
- { name: "[Stacks] pazny.<service> render", ansible.builtin.include_role: { name: pazny.<service>, apply: { tags: ['<service>'] } }, when: "install_<service> | default(false)", tags: ['<service>'] }
​```

## 7. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update (pokud přidává stack do active list)
(Upravit jen pokud služba je V EXISTUJÍCÍM stacku který už není vždy aktivní. Pokud tvůj stack už je `iiab` nebo podobný "vždy aktivní" stack, přeskoč.)

## 8. `tasks/stacks/stack-up.yml` — post.yml include (jen pokud role má `post.yml`)
​```yaml
- { name: "[Stacks] pazny.<service> post", ansible.builtin.include_role: { name: pazny.<service>, tasks_from: post.yml, apply: { tags: ['<service>'] } }, when: "install_<service> | default(false)", tags: ['<service>'] }
​```

## 9. Database provisioning (pokud service používá DB)
### Postgres
Insert into `tasks/stacks/core-up.yml` postgres provision block:
​```yaml
- { name: "<service> DB", db: "<service>", owner: "<service>", password: "{{ <service>_db_password }}" }
​```
### MariaDB
Obdobně pro MariaDB block.

## 10. Nginx vhost (dokumentace)
Uveď přesnou cestu + že se aktivuje automaticky přes `install_<service>` flag.

## 11. Smoke test
Po `ansible-playbook main.yml -K -e install_<service>=true --tags <service>` ověř:
- `docker ps | grep <service>`  → Up
- `curl -k https://<service>.dev.local` → 200
- Authentik login redirect (pokud OIDC)
```

## 10. Nový stack (jen pro agenty které ho zakládají)

Pokud tvoje role zakládá nový stack (např. `mail`, `health`, `engineering` — parent ti to řekne explicitně v prompt), pak musíš VYTVOŘIT:
- `templates/stacks/<stack>/docker-compose.yml.j2` — base s `services: {}` + `networks: { <stack>_net: driver: bridge }`
- V INTEGRATION.md sekci 7 popiš úpravu `_remaining_stacks` + přidání `tasks/stacks/stack-up.yml` deploy bloku.

## 11. Kvalita — co parent zkontroluje

- ✅ `python3 -c "import yaml; yaml.safe_load(open('roles/pazny.<service>/defaults/main.yml'))"` → OK
- ✅ `python3 -c "import yaml; yaml.safe_load(open('roles/pazny.<service>/tasks/main.yml'))"` → OK
- ✅ `python3 -c "import yaml; yaml.safe_load(open('roles/pazny.<service>/meta/main.yml'))"` → OK
- ✅ Compose template je validní Jinja2 + validní docker-compose YAML po renderu
- ✅ Port unikátní (projekt grep)
- ✅ Všechny secrets jdou přes `{{ global_password_prefix }}_pw_*` pattern
- ✅ Žádný hardcoded `dev.local` — vždy `{{ instance_tld | default('dev.local') }}`
- ✅ INTEGRATION.md je úplný a přesný
- ✅ Čistý commit na své větvi, žádné nesouvisející soubory

## 12. Shrnutí workflow agenta

1. Přečti tento brief a TVŮJ service-specific prompt (od parent agenta).
2. Přečti 1–2 referenční existující role (řekne ti je parent).
3. Vytvoř všechny deliverables dle sekce 8.
4. Validuj YAML + checkuj porty.
5. Commituj na své větvi (Conventional Commits, bez Co-Authored-By).
6. Vrať parentu krátký report: co jsi udělal, branch name, případná rizika/nejasnosti.
