# INTEGRATION: pazny.onlyoffice

Tento dokument popisuje vsechny zmeny mimo `roles/pazny.onlyoffice/`, ktere musi parent agent (orchestrator) mechanicky aplikovat pri merge teto role do `dev`.

## 1. `default.config.yml` — install toggle

Vloz do bloku `# ── B2B stack (CRM/ERP/helpdesk/chat/wiki) ──` (kolem radku 145–148),
za radku `install_outline: ...`:

```yaml
install_onlyoffice: false        # ONLYOFFICE Document Server – collaborative docs backend [Docker, JWT]
```

## 2. `default.config.yml` — `authentik_oidc_apps` entry (proxy auth)

Append do `authentik_oidc_apps:` listu (kolem radku 1566, pred helper vars block v okoli radky 1610).
ONLYOFFICE je **backend service** — proxy auth chrani pouze UI; API endpointy jsou
bez auth (JWT validace na ONLYOFFICE side).

```yaml
  - name: "ONLYOFFICE"
    slug: "onlyoffice"
    enabled: "{{ install_onlyoffice | default(false) }}"
    launch_url: "https://{{ onlyoffice_domain | default('office.dev.local') }}"
    external_host: "https://{{ onlyoffice_domain | default('office.dev.local') }}"
    type: "proxy"
```

## 3. `default.config.yml` — helper vars

Neni treba (proxy auth → neni OIDC client_id/secret).

## 4. `default.config.yml` — `authentik_app_tiers` entry

Vloz do `authentik_app_tiers:` mapy (kolem radku 1425–1448):

```yaml
  onlyoffice: 3
```

## 5. `default.credentials.yml` — nove secrets

Vloz:

```yaml
onlyoffice_jwt_secret: "{{ global_password_prefix }}_pw_onlyoffice_jwt"
```

Hodnota je fallback pro ne-blank runy. Pri `blank=true` se secret prepisuje auto-generovanou hodnotou v `main.yml` (viz sekce 6).

## 6. `main.yml` — auto-generated secret block

Vloz do "Auto-regenerate stateless secrets (every run — safe group)"
(`main.yml` kolem radku 372–380):

```yaml
        onlyoffice_jwt_secret: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
```

Pozn.: `onlyoffice_jwt_secret` je **stateless** — JWT je jen API signing, neslouzi
k sifrovani perzistentnich dat. Safe skupina je spravna volba (regeneruje se
kazdy run a je synchronizovana s hostitelskymi aplikacemi pres Ansible templates).
**Pokud je secret sdileny s externi aplikaci**, ktera ho nesleduje Ansible
playbookem (napr. Nextcloud s manualni konfiguraci), zvaz ho presunout do
destructive skupiny a synchronizovat manualne.

## 7. `tasks/stacks/stack-up.yml` — role include

Vloz do bloku `# B2B roles` (kolem radku 88–91), za radku `pazny.outline render`:

```yaml
- { name: "[Stacks] pazny.onlyoffice render", ansible.builtin.include_role: { name: pazny.onlyoffice, apply: { tags: ['onlyoffice'] } }, when: "install_onlyoffice | default(false)", tags: ['onlyoffice'] }
```

## 8. `tasks/stacks/stack-up.yml` — `_remaining_stacks` update

Uprav vyraz pro detekci b2b stacku (kolem radku 109):

**Puvodne:**
```yaml
((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false)) | ternary(['b2b'], []))
```

**Nove:**
```yaml
((install_erpnext | default(false) or install_freescout | default(false) or install_outline | default(false) or install_onlyoffice | default(false)) | ternary(['b2b'], []))
```

## 9. `tasks/stacks/stack-up.yml` — post.yml include

Neni treba — role nema `tasks/post.yml`.

## 10. Database provisioning

Neni treba — ONLYOFFICE CE pouziva **embedded postgres** uvnitr kontejneru
(bind mount `{{ onlyoffice_db_dir }}:/var/lib/postgresql`). Zadny zapis do
core-up.yml postgres/mariadb bloku.

## 11. Nginx vhost

Cesta: `templates/nginx/sites-available/onlyoffice.conf`

Aktivuje se automaticky pres `install_onlyoffice` flag (existujici auto-enable
pattern v `tasks/nginx/`). Zadny zapis do `nginx_sites_enabled` neni potreba.

### Architektura location blocks (DULEZITE)

Vhost ma **2 location bloky** s odlisnou autorizacni politikou:

- **`location /`** (UI paths: `/welcome`, admin panel, static web assets)
  - **Authentik forward_auth = ON** (chrani UI pred verejnym pristupem)
  - WebSocket upgrade headers (real-time collab)
  - Velke buffery (client_max_body_size 100m, proxy_buffer_size 32k)

- **`location ~ ^/(healthcheck|ConvertService\.ashx|coauthoring|OfficeWeb|cache|info|[0-9.]+/).*$`** (API + embed + versioned assets)
  - **Authentik forward_auth = OFF** (hostitelske aplikace volaji s JWT tokenem)
  - Stejne buffery + WebSocket headers jako `/`
  - ONLYOFFICE validuje JWT podpis na svem side → bezpecnost zachovana

Bez tohoto split by Nextcloud iframe nebyl schopen zavolat
`https://office.dev.local/ConvertService.ashx` (byl by zablokovan Authentikem
i s validnim JWT).

## 12. Smoke test

Po `ansible-playbook main.yml -K -e install_onlyoffice=true --tags onlyoffice`:

```bash
# Container running
docker ps | grep onlyoffice

# UI je za Authentikem (302 → auth.dev.local)
curl -sk -o /dev/null -w "%{http_code}\n" https://office.dev.local/
# ocekavano: 302

# API endpoint JE pristupny (proxy passthrough, JWT validace na ONLYOFFICE)
curl -sk https://office.dev.local/healthcheck
# ocekavano: "true"

# Conversion endpoint (bez JWT -> 403 z ONLYOFFICE, ale nginx ho propusti)
curl -sk -o /dev/null -w "%{http_code}\n" https://office.dev.local/ConvertService.ashx
# ocekavano: 403 nebo 200 (ne 302 na Authentik!)
```

## 13. Integracni dodatek — napojeni hostitelskych aplikaci

Pro integraci s **Nextcloud**:
1. Nextcloud UI → Apps → instaluj `ONLYOFFICE` (official connector)
2. Settings → ONLYOFFICE:
   - **Document Editing Service URL**: `https://office.dev.local/`
   - **Secret key (JWT)**: hodnota `onlyoffice_jwt_secret` z `credentials.yml`
   - **JWT Header**: `Authorization` (default)

Pro **BookStack**: ONLYOFFICE module → stejne 2 hodnoty.

Pro **Outline**: neni oficialni ONLYOFFICE plugin; Outline pouziva vlastni
prosemirror editor. ONLYOFFICE se v devBoxNOS hodi primarne pro
Nextcloud-based document workflow.
