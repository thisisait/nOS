# devBoxNOS Fleet Architecture

## Hierarchie

```
Czechbot.eu (Provider BoxNOS)
│
├── Klient: ACME Corp
│   ├── HQ Box       (acme-hq.box)      — centrala, IT, management
│   ├── Factory Box   (acme-fab1.box)    — vyrobni zavod Brno
│   ├── Factory Box   (acme-fab2.box)    — vyrobni zavod Ostrava
│   └── Sales Box     (acme-sales.box)   — obchodni oddeleni Praha
│
├── Klient: Beta s.r.o.
│   └── Office Box    (beta.box)         — jedina pobocka
│
└── Klient: Gamma Group
    ├── Division A     (gamma-div-a.box)  — divize strojirenstvi
    ├── Division B     (gamma-div-b.box)  — divize elektro
    └── Shared Services(gamma-shared.box) — HR, finance, IT
```

## Role Model

| Role | Scope | Prava |
|------|-------|-------|
| **Provider Admin** | Vsechny boxy vsech klientu | Plny pristup = CEO. Remote Ansible, fleet dashboard, config audit, backup management. |
| **Client CEO** | Vsechny boxy klienta | Plny pristup ke vsem sluzbam. Sprava uzivatelu, konfigurace, data. |
| **Division Admin** | Jeden box / divize | Lokalni admin. Sprava sluzeb, uzivatelu v ramci sve divize. |
| **Power User** | Jeden box | Pristup ke vsem povolenym sluzbam. Nemuze menit konfiguraci. |
| **User** | Jeden box | Pristup jen k vybranym sluzbam (Nextcloud, Open WebUI, Outline). |
| **Guest** | IIAB Terminal | SSH TUI only. Kiwix, knihy, AI chat. Zadny admin pristup. |

## Authentik Group Mapping

```yaml
# Skupiny v Authentiku (vytvorene automaticky pri blank run)
authentik_default_groups:
  - name: "devboxnos-providers"
    description: "Provider admins (Czechbot.eu) — full remote access"
    role: "provider-admin"
  - name: "devboxnos-admins"
    description: "Client CEO/CTO — full local + remote access"
    role: "client-admin"
  - name: "devboxnos-managers"
    description: "Division/department managers"
    role: "division-admin"
  - name: "devboxnos-users"
    description: "Standard employees"
    role: "user"
  - name: "devboxnos-guests"
    description: "Guest/IIAB terminal access only"
    role: "guest"
```

## Provider Remote Access

Provider (Czechbot.eu) ma vzdaleny pristup ke vsem klientskym boxum:

### 1. Tailscale Mesh
- Kazdy box se pripoji do providerskeho tailnetu
- Provider vidi vsechny boxy v jedne siti
- ACL policy: provider nodes → client boxes (full access)

### 2. Heartbeat Reporting
- Kazdy box posila status kazdych 5 minut na `fleet.czechbot.eu/api/heartbeat`
- Provider dashboard zobrazuje: vsechny boxy, zdravi sluzeb, verze, uptime

### 3. Box API (Remote Execution)
- Provider muze volat `POST /api/run-tag` na libovolnem boxu
- Autentizace: API key + Tailscale ACL (double check)
- Povolene akce: update, verify, backup, nginx restart

### 4. Authentik Federation (budoucnost)
- Provider Authentik jako upstream IdP
- Klientsky Authentik deleguje autentizaci na provider
- Single sign-on across all client boxes

### 5. Puter as Management UI
- Provider pouziva Puter na svem BoxNOS jako management dashboard
- Puter iframe apps: fleet overview, box detail, remote terminal
- Budoucnost: custom Puter app "Fleet Manager"

## Instance Configuration

```yaml
# config.yml na klientskem boxu
instance_name: "acme-hq"
instance_tld: "acme.box"
instance_org: "ACME Corp"
instance_location: "Praha, CZ"
instance_role: "headquarters"          # headquarters | factory | office | division | shared
instance_parent: ""                    # slug nadrazeneho boxu (pro hierarchii)

# Fleet reporting
configure_heartbeat: true
heartbeat_endpoint: "https://fleet.czechbot.eu/api/heartbeat"
heartbeat_api_key: "{{ provider_api_key }}"

# Provider access
provider_admin_email: "admin@czechbot.eu"
provider_tailscale_tag: "tag:provider"
```

## Sitova topologie

```
┌──────────────────────────────────────────────────────────┐
│                    Tailscale Mesh                         │
│                                                          │
│  ┌──────────────┐     ┌──────────────┐                  │
│  │ Provider Box │────▶│ Client HQ    │                  │
│  │(czechbot.eu) │     │(acme-hq.box) │                  │
│  │              │     │              │                  │
│  │ Fleet Mgmt   │     │ Authentik    │◀─── SSO ────┐   │
│  │ Heartbeat RX │     │ (master IdP) │              │   │
│  │ Puter UI     │     └──────┬───────┘              │   │
│  └──────────────┘            │                      │   │
│         │                    │ Tailscale             │   │
│         │              ┌─────┴─────┐                │   │
│         │              │           │                │   │
│         ▼              ▼           ▼                │   │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │ Client Fab1  │ │Client Fab2│ │Client Sales│      │   │
│  │(acme-fab1)   │ │(acme-fab2)│ │(acme-sales)│─────┘   │
│  │              │ │          │ │           │            │
│  │ Local apps   │ │Local apps│ │ Local apps│            │
│  │ Heartbeat TX │ │Heartbeat │ │ Heartbeat │            │
│  └──────────────┘ └──────────┘ └───────────┘            │
└──────────────────────────────────────────────────────────┘
```

## Datovy tok

1. **Provisioning**: Provider forkne repo → nastavi config.yml → dodá Mac klientovi
2. **Bootstrap**: Klient spusti `provision-client.sh` → playbook → box ready
3. **Operation**: OpenClaw + zamestnanci pouzivaji sluzby
4. **Monitoring**: Heartbeat → Provider fleet dashboard
5. **Update**: Provider pushne update do forku → klient pulls → Woodpecker re-provision
6. **Backup**: Restic → lokalni/S3 uloziste
7. **Migration**: Export state → novy HW → import state

## Puter jako Management UI

Puter na provider BoxNOS slouzi jako vizualni rozhrani pro spravu fleet:

### Iframe Apps (planovane)
- **Fleet Dashboard** (`fleet.czechbot.eu`) — prehled vsech boxu, zdravi, alerty
- **Box Detail** (`box-detail.czechbot.eu`) — detail jednoho boxu, logy, metriky
- **Remote Terminal** (`term.czechbot.eu`) — SSH pres browser do libovolneho boxu
- **Config Editor** (`config.czechbot.eu`) — editace config.yml klientskeho boxu

### API Integration
- Puter volá Box API (`/api/health`, `/api/status`) kazdého klienta
- Zobrazuje data v custom Puter apps (HTML/JS iframe)
- Autentizace pres Tailscale + API key

## Bezpecnostni model

1. **Network**: Tailscale (WireGuard) — sifrovany, zero-trust
2. **Identity**: Authentik OIDC — centralni SSO per box
3. **Secrets**: Infisical — per-box secrets vault
4. **API**: Bearer tokens + Tailscale ACL double-check
5. **Audit**: Authentik event log + Grafana Loki
6. **Backup**: Restic (sifrovany, offsite)
