# nOS — the engine behind AIT

> **One stack. Forty services. Zero SaaS bills.**
>
> `nOS` is the open-source integration engine behind [**This is AIT — Agentic IT**](https://thisisait.eu).
> An Ansible playbook that orchestrates 45+ roles, wires 40+ FOSS services together through one SSO,
> and turns an Apple Silicon Mac into a reproducible, self-hosted, self-managing cloud.

<p align="center">
  <a href="https://thisisait.eu">thisisait.eu</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#the-stack">Stack</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#sso--rbac">SSO &amp; RBAC</a> ·
  <a href="#configuration">Configuration</a>
</p>

---

## What it is

`nOS` is the reference implementation of **AIT — Agentic IT**: a new category of self-hosted, agentic,
open-source infrastructure that collapses the SaaS stack back onto a single machine on your desk.

- **One command** wipes a Mac, installs 40+ services, integrates them, and secures them.
- **One SSO** (Authentik) fronts every app — OIDC where possible, forward-auth where not.
- **One vault** (Infisical) owns every secret. Per-tenant personal vaults via Vaultwarden.
- **One agent** (OpenClaw + Ollama MLX) runs DevOps tasks locally, no API key required.
- **One command** again brings everything back on a fresh box — `blank=true`, ~20 minutes.

This is not a homelab hobby. It's what replaces Notion + GitHub + 1Password + Vercel +
Grafana Cloud + Auth0 + Slack + Zoom for a developer or a small team.

---

## What it replaces

| You're paying for | You could self-host | via nOS role |
|---|---|---|
| Notion / Confluence | Outline, HedgeDoc, BookStack | `pazny.outline`, `pazny.hedgedoc`, `pazny.bookstack` |
| GitHub / GitLab.com | Gitea, GitLab CE + Woodpecker CI | `pazny.gitea`, `pazny.gitlab`, `pazny.woodpecker` |
| 1Password / LastPass | Vaultwarden (personal) + Infisical (infra) | `pazny.vaultwarden`, `pazny.infisical` |
| Auth0 / Okta | Authentik (OIDC + forward-auth + RBAC) | `pazny.authentik` |
| Grafana Cloud / Datadog | Grafana + Prometheus + Loki + Tempo + Alloy | `pazny.grafana`, `pazny.prometheus`, `pazny.loki`, `pazny.tempo` |
| ChatGPT / Claude.ai | Open WebUI + Ollama (MLX on Apple Silicon) | `pazny.open_webui`, `pazny.openclaw` |
| Slack / Discord | Hermes cross-channel gateway (optional) | `pazny.hermes` |
| Dropbox / Google Drive | Nextcloud + OnlyOffice | `pazny.nextcloud`, `pazny.onlyoffice` |
| Zapier / Make | n8n + Node-RED | `pazny.n8n`, `pazny.nodered` |
| Linear / Jira | ERPNext, FreeScout | `pazny.erpnext`, `pazny.freescout` |
| QuickBooks | Firefly III | `pazny.firefly` |
| Metabase Cloud | Metabase, Superset | `pazny.metabase`, `pazny.superset` |
| Netflix / Plex Pass | Jellyfin | `pazny.jellyfin` |
| Portainer Business | Portainer CE | `pazny.portainer` |

Hardware and electricity not included. A Mac Mini M4 pays for itself in under a year for a typical power user.

---

## Quick start

> **Target:** macOS on Apple Silicon (M1+). Intel Macs are not supported.
> **Recommended:** 36 GB RAM, 1 TB external SSD (nOS tiers heavy data onto it automatically).

### 1. Bootstrap

```bash
git clone https://github.com/thisisait/nOS.git ~/nOS
cd ~/nOS
./bootstrap.sh      # Xcode CLT → Homebrew → Ansible → Galaxy roles → config scaffolding
```

### 2. Configure

Bootstrap creates two gitignored files — `config.yml` and `credentials.yml`. Edit both:

```bash
$EDITOR config.yml          # feature toggles: which services to install
$EDITOR credentials.yml     # set global_password_prefix, override per-service secrets
```

Passwords follow the pattern `{global_password_prefix}_pw_{service}`. Override any you care
about in `credentials.yml`; the rest are derived. Generator: `openssl rand -hex 32`.

### 3. Run

```bash
# Full install (prompts for sudo)
ansible-playbook main.yml -K

# Clean reinstall — wipes ALL data and secrets, prompts for a new prefix, rebuilds from scratch
ansible-playbook main.yml -K -e blank=true

# Run a single stack
ansible-playbook main.yml -K --tags "stacks,observability"
```

A full first run takes **~20 minutes** on an M4 Pro with fast internet.

---

## The stack

Every Docker service is owned by an Ansible role under `roles/pazny.*`. Services are
grouped into **8 Docker Compose stacks** that boot in dependency order.

| Stack | Role count | Services |
|---|---|---|
| **infra** (always on, always first) | 9 | MariaDB, PostgreSQL, Redis, Portainer, Traefik, Authentik (server + worker), Infisical, Bluesky PDS |
| **observability** (always on, always second) | 4 | Grafana, Prometheus, Loki, Tempo (+ Alloy as unified collector on the host) |
| **iiab** — Internet-in-a-Box & productivity | 12 | WordPress, Nextcloud, n8n, Kiwix, Jellyfin, Open WebUI, Uptime Kuma, Calibre-Web, Home Assistant, RustFS, Puter, Vaultwarden |
| **devops** | 5 | Gitea, Woodpecker CI, GitLab CE, Paperclip, code-server |
| **b2b** | 7 | ERPNext, FreeScout, Outline, HedgeDoc, BookStack, Firefly III, OnlyOffice |
| **voip** | 1 | FreePBX (Asterisk) |
| **engineering** | 1 | QGIS Server |
| **data** | 2 | Metabase, Apache Superset |

Non-Docker services installed directly on the host: **OpenClaw** (launchd agent daemon),
**Wing** (Nette PHP security dashboard), **Bone** (local management REST bridge),
**IIAB Terminal** (Python Textual TUI over SSH).

---

## Architecture

### Compose-override pattern

Each role owns a single Docker Compose fragment that is merged into its stack at runtime:

```
roles/pazny.<service>/
  defaults/main.yml          # version, port, data_dir, mem_limit
  tasks/main.yml             # render override file into ~/stacks/<stack>/overrides/
  tasks/post.yml             # (optional) API calls, DB init, admin bootstrap
  templates/compose.yml.j2   # service definition — no top-level networks:
  handlers/main.yml          # (optional) restart handler
```

Stack orchestrators (`tasks/stacks/core-up.yml`, `stack-up.yml`) discover overrides with
`ansible.builtin.find` and pass them as `-f` flags to `docker compose up`:

```bash
docker compose \
  -f ~/stacks/iiab/docker-compose.yml \
  -f ~/stacks/iiab/overrides/wordpress.yml \
  -f ~/stacks/iiab/overrides/nextcloud.yml \
  ... \
  up iiab --wait
```

**Result:** each service stays in its own role, but the stack sees one merged compose. Add a
service by creating a role — no hand-edits to the base stack template.

### Boot order

1. **Password prefix prompt** (on `blank=true`)
2. **Blank reset** — wipes Docker, data dirs, external SSD paths
3. **Auto-enable dependencies** — flips on MariaDB/PostgreSQL/Redis based on which services are on
4. **Auto-generate secrets** — Outline, Bluesky, Authentik bootstrap token, Infisical, Vaultwarden, Paperclip
5. **Host-level roles** — Xcode CLT → Homebrew → dotfiles → Mac App Store → Dock
6. **Host tasks** — macOS defaults, SSH, language runtimes (PHP, Node, Python, Go, .NET, Bun), Nginx, external storage tiering
7. **Core stacks up** — `infra` + `observability` (always required, always first)
8. **Post-start core** — Authentik blueprints + OIDC app provisioning, Infisical init, PDS bootstrap, Portainer admin + OAuth
9. **Remaining stacks up** — `iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`
10. **Post-start services** — admin users, DB migrations, OIDC wiring, onboarding
11. **Tier-2 apps stack** — `pazny.apps_runner` discovers `apps/<name>.yml` manifests,
    validates them (GDPR Article 30 + TLS / SSO / EU-residency gates), renders
    a merged compose override, brings the apps stack up, fires observability
    hooks. See [docs/tier2-app-onboarding.md](docs/tier2-app-onboarding.md).
12. **Post-provision** — stack health verification, service registry

**Invariant:** post-start tasks can assume MariaDB, PostgreSQL, Authentik, Infisical,
Grafana, Loki, and Tempo are already online.

### Reverse proxy

Traefik in a container is the default edge proxy (binds 80/443) as of C1
(2026-04-29). Two providers: **file** (auto-derived from `state/manifest.yml`
for the 50+ existing Tier-1 services) and **docker** (auto-emitted labels
for Tier-2 apps_runner manifests). Authentik forward-auth wires through
the `authentik@file` middleware. Host nginx is opt-in via
`install_nginx: true` and lives behind the same `tasks/nginx.yml`. See
[docs/traefik-primary-proxy.md](docs/traefik-primary-proxy.md).

### State & Migration Framework

Long-lived installs get a first-class answer to "what's running, how do I safely change
it, and how do I roll back". Four surfaces: declarative state
(`state/manifest.yml` + `~/.nos/state.yml`), global migrations
(`migrations/*.yml`, auto-applied in `pre_tasks`), per-service upgrade recipes
(`upgrades/*.yml`, including `pg_upgrade` / `mariadb-upgrade` / Grafana
dashboard-preserving patterns), and dual-version coexistence for zero-downtime major
upgrades. Every action emits structured events to Wing
(`/migrations`, `/upgrades`, `/timeline`, `/coexistence` views).

See [docs/framework-overview.md](docs/framework-overview.md) for the operator tour,
and [docs/framework-plan.md](docs/framework-plan.md) for the authoritative spec.

---

## SSO & RBAC

Single sign-on is not optional in `nOS` — most services are fronted by Authentik at
`auth.<tld>` (default `auth.dev.local`). Each Tier-1 plugin under
`files/anatomy/plugins/<svc>-base/plugin.yml` carries its own `authentik:` block;
the `authentik-base` aggregator harvests them into `inputs.clients` and the plugin
loader renders them into the live Authentik blueprint at deploy time. Post-start
tasks auto-provision OIDC providers and applications for every enabled service.

### Integration modes

| Mode | Services | How |
|---|---|---|
| **Native OIDC (env)** | Grafana, Outline, Open WebUI, n8n, GitLab, Vaultwarden | OIDC env vars in the compose override |
| **Native OIDC (API/CLI)** | Gitea, Nextcloud, Portainer | Admin API / `occ` / PUT `/api/settings` |
| **Proxy auth** (forward-auth) | Uptime Kuma, Calibre-Web, Home Assistant, Jellyfin, Kiwix, WordPress, ERPNext, FreeScout, Infisical, Paperclip, Superset, Puter, Metabase | Nginx `auth_request` + Authentik embedded outpost |
| **Identity bridge** | Bluesky PDS | Authentik → PDS auto-provisions `@user.bsky.<tld>` accounts |
| **No SSO** | FreePBX, QGIS | Service owns its own auth |

Proxy auth *gates access* but each service still renders its own login. Native OIDC gives
you a real "Sign in with Authentik" button.

### RBAC tiers

Four access tiers, bound to Authentik groups via expression policies. Every app's tier is
declared in `authentik_app_tiers`; users are added to the corresponding `nos-*` group
(installs provisioned before 2026-04-22 use the legacy `devboxnos-*` prefix — rename the groups in Authentik or run `blank=true` to regenerate).

| Tier | Role | Scope | Example services |
|---|---|---|---|
| 1 | **admin** | Infra, secrets, monitoring | Portainer, Infisical, Grafana, Wing, InfluxDB |
| 2 | **manager** | Dev tools, analytics, automation | Gitea, GitLab, n8n, Superset, Metabase, Paperclip, ERPNext, FreeScout |
| 3 | **user** | Employee productivity | Nextcloud, Outline, Open WebUI, Puter, Vaultwarden, Uptime Kuma, Home Assistant, Calibre-Web |
| 4 | **guest** | Public/content | Kiwix, Jellyfin, WordPress |

---

## Configuration

### Layering

Four files, later overrides earlier:

```
default.config.yml        ← all variables with defaults                (committed)
default.credentials.yml   ← all secrets as {{ prefix }}_pw_*  templates (committed)
config.yml                ← your feature toggles                        (gitignored)
credentials.yml           ← your secret overrides                       (gitignored)
```

### Installation queue

The top of `default.config.yml` is a flat list of ~78 boolean toggles — comment out
anything you don't want:

```yaml
install_nginx: true
install_openclaw: true            # AI agent + Ollama MLX
install_observability: true       # LGTM stack (required for audit trail)

install_wordpress: false
install_nextcloud: true
install_gitea: true
install_gitlab: false             # heavy (~4 GB RAM); only enable if you need CI at scale
install_open_webui: true
# ... 70 more
```

### Version policy

```bash
ansible-playbook main.yml -K                           # stable (default, CVE-patched)
ansible-playbook main.yml -K -e version_policy=latest  # track upstream latest
ansible-playbook main.yml -K -e version_policy=lts     # LTS branches where available
./security-update.sh                                   # security-only pull
```

Per-service override: set `{service}_version` in `config.yml`.

### Instance identity

Every `nOS` box has a unique identity so a provider (e.g. [thisisait.eu](https://thisisait.eu)) can manage a fleet:

```yaml
instance_name: "nos"                 # unique slug
instance_tld: "dev.local"            # every service lives at <service>.<tld>
instance_role: "standalone"          # standalone | headquarters | factory | office | division
instance_parent: ""                  # slug of parent box for hierarchy
```

---

## Tags & selective runs

```bash
ansible-playbook main.yml -K --tags "TAG[,TAG…]"
```

| Tag | What runs |
|---|---|
| `stacks` | All Docker stacks |
| `core`, `infra`, `observability` | Core stacks only |
| `nginx` | Nginx + vhosts + mkcert certs |
| `php`, `node`, `python`, `go`, `dotnet`, `bun` | Single language runtime |
| `openclaw`, `hermes`, `ai` | AI agents |
| `wing`, `security` | Wing security dashboard |
| `iiab-terminal`, `ssh` | SSH + ForceCommand TUI |
| `bone`, `api` | Local FastAPI (structure / state / dispatcher) |
| `dnsmasq`, `dns`, `network` | `*.<tld>` resolver |
| `tailscale` | VPN |
| `external-storage`, `storage` | Tier data onto `/Volumes/*` |
| `macos-defaults`, `osx` | Finder / Dock / keyboard / screenshot prefs |
| `backup` | Restic backup config |
| `heartbeat`, `fleet` | Fleet reporting daemon |
| `blank`, `reset` | Blank-wipe tasks (requires `-e blank=true`) |

Dry run: `--check`. Syntax only: `ansible-playbook main.yml --syntax-check`.

---

## External storage

If `configure_external_storage: true` and an SSD is mounted at `external_storage_root`
(default `/Volumes/SSD1TB`), heavy data directories are bind-mounted onto it — GitLab,
Ollama models, observability databases, media libraries, Docker Desktop disk image location,
language caches:

```
/Volumes/SSD1TB/
├── cache/{npm,pip,composer,homebrew}/
├── docker/                 # Docker Desktop disk image (manual move via Settings)
├── gitea/  gitlab/  woodpecker/
├── ollama/models/          # ~17 GB per LLM
├── observability/{prometheus,loki,tempo}/
├── media/  jellyfin/
├── kiwix/  maps/           # ZIMs + MBTiles
├── nextcloud-data/  wordpress/  calibre/
└── n8n/  openwebui/  portainer/  uptime-kuma/
```

`blank=true` honors these paths — it wipes the real data, not just empty `~/service`
fallback directories.

---

## Adding a new service

**Tier-1 (full role + plugin):**

1. Scaffold the role under `roles/pazny.<service>/` following the compose-override pattern.
2. Wire it into the right stack orchestrator (`tasks/stacks/core-up.yml` or `stack-up.yml`)
   with `include_role` — remember both `apply: { tags: […] }` **and** `tags: […]` on the
   task so `--tags` filtering works.
3. Add `install_<service>: false` to `default.config.yml`.
4. Create `files/anatomy/plugins/<service>-base/plugin.yml` with an `authentik:` block
   (mirror an existing sibling such as `grafana-base/plugin.yml`). The plugin loader
   harvests it into the Authentik blueprint automatically.
5. Add a row to `state/manifest.yml` with `domain_var` + `port_var` so Traefik's
   file-provider auto-routes the service.

**Tier-2 (manifest-only — no role):** drop a YAML at `apps/<service>.yml` and re-run the
playbook. See [docs/tier2-app-onboarding.md](docs/tier2-app-onboarding.md) for the
GDPR-gated manifest schema and Coolify import flow.

The full doctrine for both paths lives in [CLAUDE.md](CLAUDE.md) §Adding a new
Docker service.

---

## Manual steps macOS can't automate

| # | What | Why |
|---|---|---|
| 1 | `tailscale up` | Interactive browser login |
| 2 | System Settings → Keyboard → Modifier Keys → Caps Lock → Escape | Per-keyboard, not scriptable |
| 3 | System Settings → Privacy & Security → Full Disk Access → add Terminal / Ghostty | SIP-protected |
| 4 | Docker Desktop → Settings → Resources → Disk image location → `/Volumes/SSD1TB/docker/` | GUI-only |

mkcert CA install and `*.<tld>` DNS are automated via `dnsmasq` + `/etc/resolver/<tld>`.

---

## Project layout

```
nOS/
├── main.yml                         # entry point: handlers + imports
├── bootstrap.sh  bootstrap/         # Xcode CLT → Homebrew → Ansible → config scaffolding
├── default.config.yml               # all variables (committed)
├── default.credentials.yml          # secret templates (committed)
├── config.yml  credentials.yml      # your overrides (gitignored)
├── requirements.yml                 # Galaxy role dependencies
├── inventory                        # Ansible inventory (localhost)
├── security-update.sh               # security-only image pull
│
├── roles/pazny.<service>/           # 57 roles, one per service
│   ├── defaults/  tasks/  handlers/  templates/  meta/
│   └── templates/compose.yml.j2     # compose-override fragment
│
├── tasks/
│   ├── stacks/
│   │   ├── core-up.yml              # infra + observability (always first)
│   │   ├── stack-up.yml             # iiab, devops, b2b, voip, engineering, data
│   │   ├── authentik_service_post.yml
│   │   ├── bluesky_pds_bridge.yml
│   │   ├── external-paths.yml       # honor /Volumes/SSD1TB overrides
│   │   └── shared-network.yml
│   ├── blank-reset.yml              # wipes Docker, data, configs
│   ├── nginx.yml  php.yml  node.yml  python.yml  golang.yml  dotnet.yml  bun.yml
│   ├── observability.yml            # Alloy + scrape targets
│   ├── macos-defaults.yml  osx.yml
│   ├── backup.yml  heartbeat.yml  vulnerability-scan.yml
│   ├── system-services.yml  tailscale.yml  dnsmasq.yml
│   ├── external-storage.yml  power-management.yml
│   └── service-registry.yml  export-state.yml  import-state.yml
│
├── templates/
│   ├── stacks/{infra,observability,iiab,devops,b2b,voip,engineering,data}/
│   │   └── docker-compose.yml.j2    # base stack (services: {} + networks)
│   └── nginx/sites-available/       # 50 vhosts
│
├── files/                           # static assets (configs, dashboards, icons)
├── docs/                            # architecture notes, fleet-architecture.md
└── tests/
```

---

## Known tech debt

- `ansible_env` → `ansible_facts.env` migration needed before Ansible-core 2.24
- Bluesky PDS federation needs public DNS to be fully functional (account bridge works locally)
- ERPNext first-run migration sometimes fails; `erpnext_post.yml` has an auto-retry
- Jellyfin / Open WebUI may restart-loop on first DB init until data regenerates — expected
- Mattermost removed (no ARM64 FOSS image); config retained for future

---

## Contributing

The repo is public. The category isn't written yet. Help us define it.

- Star the repo → it's how open source gets found
- File issues with real traces — `docker compose logs`, `ansible-playbook -vv`
- PRs follow Conventional Commits (`feat:`, `fix:`, `refactor:`…). No `Co-Authored-By`, no `--author`.
- Primary branch is `master`. Short-lived `feat/*` / `fix/*` branches merge back via FF or PR.

---

## Origin & license

Main inspiration: [IIAB - internet in a box](https://github.com/iiab/iiab)

Forked from [geerlingguy/mac-dev-playbook](https://github.com/geerlingguy/mac-dev-playbook)
by [Jeff Geerling](https://www.jeffgeerling.com/), author of
[Ansible for DevOps](https://www.ansiblefordevops.com/).

MIT Licensed. Sent from my Mac Studio. **Built by humans, maintained by agents.**

Website: [thisisait.eu](https://thisisait.eu)
