# nOS Fleet Architecture

## Hierarchy

```
thisisait.eu (Provider BoxNOS)
│
├── Client: ACME Corp
│   ├── HQ Box        (acme-hq.box)       - headquarters, IT, management
│   ├── Factory Box   (acme-fab1.box)     - Brno production plant
│   ├── Factory Box   (acme-fab2.box)     - Ostrava production plant
│   └── Sales Box     (acme-sales.box)    - Prague sales department
│
├── Client: Beta s.r.o.
│   └── Office Box    (beta.box)          - single branch
│
└── Client: Gamma Group
    ├── Division A     (gamma-div-a.box)  - mechanical engineering division
    ├── Division B     (gamma-div-b.box)  - electrical division
    └── Shared Services(gamma-shared.box) - HR, finance, IT
```

## Role Model

| Role | Scope | Permissions |
|------|-------|-------------|
| **Provider Admin** | All boxes of all clients | Full access = CEO. Remote Ansible, fleet dashboard, config audit, backup management. |
| **Client CEO** | All boxes of the client | Full access to all services. User management, configuration, data. |
| **Division Admin** | One box / division | Local admin. Manage services and users within their division. |
| **Power User** | One box | Access to all allowed services. Cannot change configuration. |
| **User** | One box | Access only to selected services (Nextcloud, Open WebUI, Outline). |
| **Guest** | IIAB Terminal | SSH TUI only. Kiwix, books, AI chat. No admin access. |

## Authentik Group Mapping

```yaml
# Groups in Authentik (created automatically during blank run)
authentik_default_groups:
  - name: "nos-providers"
    description: "Provider admins (thisisait.eu) — full remote access"
    role: "provider-admin"
  - name: "nos-admins"
    description: "Client CEO/CTO — full local + remote access"
    role: "client-admin"
  - name: "nos-managers"
    description: "Division/department managers"
    role: "division-admin"
  - name: "nos-users"
    description: "Standard employees"
    role: "user"
  - name: "nos-guests"
    description: "Guest/IIAB terminal access only"
    role: "guest"
```

## Provider Remote Access

The provider (thisisait.eu) has remote access to all client boxes:

### 1. Tailscale Mesh
- Each box joins the provider tailnet
- The provider sees all boxes in a single network
- ACL policy: provider nodes -> client boxes (full access)

### 2. Heartbeat Reporting
- Each box sends status every 5 minutes to `fleet.czechbot.eu/api/heartbeat`
- Provider dashboard shows: all boxes, service health, versions, uptime

### 3. Box API (Remote Execution)
- Provider can call `POST /api/run-tag` on any box
- Authentication: API key + Tailscale ACL (double check)
- Allowed actions: update, verify, backup, nginx restart

### 4. Authentik Federation (future)
- Provider Authentik as upstream IdP
- Client Authentik delegates authentication to the provider
- Single sign-on across all client boxes

### 5. Puter as Management UI
- Provider uses Puter on its BoxNOS as a management dashboard
- Puter iframe apps: fleet overview, box detail, remote terminal
- Future: custom Puter "Fleet Manager" app

## Instance Configuration

```yaml
# config.yml on a client box
instance_name: "acme-hq"
instance_tld: "acme.box"
instance_org: "ACME Corp"
instance_location: "Praha, CZ"
instance_role: "headquarters"          # headquarters | factory | office | division | shared
instance_parent: ""                    # slug of the parent box (for hierarchy)

# Fleet reporting
configure_heartbeat: true
heartbeat_endpoint: "https://fleet.czechbot.eu/api/heartbeat"
heartbeat_api_key: "{{ provider_api_key }}"

# Provider access
provider_admin_email: "admin@czechbot.eu"
provider_tailscale_tag: "tag:provider"
```

## Network topology

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

## Data flow

1. **Provisioning**: Provider forks the repo -> sets config.yml -> ships Mac to the client
2. **Bootstrap**: Client runs `provision-client.sh` -> playbook -> box ready
3. **Operation**: OpenClaw + employees use the services
4. **Monitoring**: Heartbeat -> Provider fleet dashboard
5. **Update**: Provider pushes an update to the fork -> client pulls -> Woodpecker re-provisions
6. **Backup**: Restic -> local/S3 storage
7. **Migration**: Export state -> new HW -> import state

## Puter as Management UI

Puter on the provider BoxNOS serves as the visual interface for fleet management:

### Iframe Apps (planned)
- **Fleet Dashboard** (`fleet.czechbot.eu`) - overview of all boxes, health, alerts
- **Box Detail** (`box-detail.czechbot.eu`) - details of a single box, logs, metrics
- **Remote Terminal** (`term.czechbot.eu`) - SSH via browser into any box
- **Config Editor** (`config.czechbot.eu`) - edit config.yml of a client box

### API Integration
- Puter calls the Box API (`/api/health`, `/api/status`) of each client
- Shows data in custom Puter apps (HTML/JS iframe)
- Authentication via Tailscale + API key

## Security model

1. **Network**: Tailscale (WireGuard) - encrypted, zero-trust
2. **Identity**: Authentik OIDC - central SSO per box
3. **Secrets**: Infisical - per-box secrets vault
4. **API**: Bearer tokens + Tailscale ACL double-check
5. **Audit**: Authentik event log + Grafana Loki
6. **Backup**: Restic (encrypted, offsite)
