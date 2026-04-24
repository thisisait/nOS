# nOS — TL;DR

> One-page cheatsheet for `nOS`, the self-hosted AIT engine.
> For the full story: [README.md](README.md).

Target: macOS on Apple Silicon (M1+). Recommended: 36 GB RAM + 1 TB external SSD.

---

## What gets installed

One `ansible-playbook` run, ~20 minutes on an M4 Pro:

| Layer | What |
|---|---|
| **Host** | Homebrew (~80 CLI + ~30 GUI casks), dotfiles, macOS defaults, dnsmasq for `*.dev.local`, mkcert CA, Nginx reverse proxy with vhost templates for PHP / Node / Python / Go / static |
| **Runtimes** | PHP 8.3 + Composer, Node.js (NVM) + npm/pnpm/yarn, Bun, Python 3.13 (pyenv), Go, .NET |
| **Core stack** (always on) | MariaDB, PostgreSQL, Redis, Traefik, Portainer, Authentik (server + worker), Infisical, Bluesky PDS |
| **Observability** (always on) | Grafana, Prometheus, Loki, Tempo, Alloy (unified collector) |
| **IIAB / productivity** | WordPress, Nextcloud, n8n, Node-RED, Kiwix, offline maps, Jellyfin, Open WebUI, Uptime Kuma, Calibre-Web, Home Assistant, RustFS, Puter, Vaultwarden, ntfy, Miniflux |
| **DevOps** | Gitea, GitLab CE, Woodpecker CI, Paperclip, code-server |
| **B2B** | ERPNext, FreeScout, Outline, HedgeDoc, BookStack, Firefly III, OnlyOffice |
| **Data** | Metabase, Apache Superset, InfluxDB |
| **VoIP / Engineering** | FreePBX (Asterisk), QGIS Server |
| **Agents** | OpenClaw (local DevOps agent, Ollama MLX), Hermes (cross-channel gateway), OpenCode, MCP gateway |
| **Host-native** | jsOS webtop (PM2), Wing security dashboard, IIAB Terminal TUI, Bone bridge |
| **Network** | Tailscale VPN, dnsmasq, optional SSH/Samba/VNC |
| **External SSD** | Tiers heavy data (Ollama models, observability DBs, media, caches, GitLab, Docker disk image) onto `/Volumes/SSD1TB` |
| **State & Migrations** | Declarative state (`~/.nos/state.yml`), auto-applied migrations (`migrations/*.yml`), per-service upgrade recipes (`upgrades/*.yml` — pg_upgrade / mariadb-upgrade / Grafana dashboard-preserving), dual-version coexistence. Live in Wing at `/migrations`, `/upgrades`, `/timeline`, `/coexistence`. See [docs/framework-overview.md](docs/framework-overview.md). |

---

## Before you run

One command replaces four manual steps:

```bash
git clone https://github.com/thisisait/nOS.git ~/nOS
cd ~/nOS
./bootstrap.sh
```

`bootstrap.sh` installs: **Xcode CLT → Homebrew → Ansible → Galaxy roles → config scaffolding**.

### Manual (if you insist)

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install ansible
git clone https://github.com/thisisait/nOS.git ~/nOS && cd ~/nOS
ansible-galaxy install -r requirements.yml
cp default.config.yml config.yml
cp default.credentials.yml credentials.yml
```

---

## Configure

Edit two gitignored files that bootstrap creates:

```bash
$EDITOR config.yml          # feature toggles (install_<service>: true|false)
$EDITOR credentials.yml     # set global_password_prefix, override per-service secrets
```

Password pattern: `{global_password_prefix}_pw_{service}`. Set the prefix once; every service secret is derived from it unless you override it explicitly. Generator for overrides: `openssl rand -hex 32`.

Mandatory external-SSD format: **APFS Case-Sensitive** (or HFS+ Journaled Case-Sensitive). Mount point: `/Volumes/SSD1TB` (or whatever `external_storage_root` points at).

---

## Run

```bash
# Full install (prompts for sudo)
ansible-playbook main.yml -K

# Clean reinstall — wipes ALL data and secrets, prompts for a new prefix
ansible-playbook main.yml -K -e blank=true

# Syntax only
ansible-playbook main.yml --syntax-check

# Dry run
ansible-playbook main.yml -K --check
```

Sudo is needed for: `/etc/resolver/<tld>` (dnsmasq), system SSH/Samba/VNC services (if enabled), and writes to `/etc/hosts`.

### Tags — selective runs

```bash
ansible-playbook main.yml -K --tags "core,observability"
ansible-playbook main.yml -K --tags "nginx"
ansible-playbook main.yml -K --tags "openclaw,ai"
ansible-playbook main.yml -K --tags "external-storage,storage"
ansible-playbook main.yml -K --tags "iiab"
ansible-playbook main.yml -K --tags "macos-defaults,osx"
```

Full tag list: see README.md § *Tags & selective runs*.

---

## Expected outcome

```
PLAY RECAP *********************************************************************
localhost  :  ok=180+  changed=95+  unreachable=0  failed=0  skipped=N  rescued=0
```

`failed=0` is the contract. `skipped` is normal — it's the toggles you left off. `changed` is high on first run, near-zero on idempotent re-runs.

### Verify

```bash
# Host services
brew services list

# DNS resolves on the loopback
dig grafana.dev.local @127.0.0.1          # -> 127.0.0.1

# Nginx serves HTTPS via mkcert
curl -fsSL https://portainer.dev.local > /dev/null

# Grafana login
open https://grafana.dev.local            # admin / <your password>

# Ollama + MLX
ollama list

# Docker stacks are up
docker compose -f ~/stacks/infra/docker-compose.yml ps
docker compose -f ~/stacks/iiab/docker-compose.yml ps
```

---

## External SSD layout

```
/Volumes/SSD1TB/
├── cache/{npm,pip,composer,homebrew}/
├── docker/                   # Docker Desktop disk image (manual move via Settings)
├── gitea/  gitlab/  woodpecker/
├── ollama/models/            # ~17 GB per LLM
├── observability/{prometheus,loki,tempo}/
├── media/  jellyfin/
├── kiwix/  maps/             # ZIMs + MBTiles
├── nextcloud-data/  wordpress/  calibre/
├── n8n/  openwebui/  portainer/  uptime-kuma/
└── rustfs/
```

`blank=true` honors these paths — wipes the real data, not just empty `~/service` fallbacks.

---

## When something breaks

| Symptom | Fix |
|---|---|
| `ansible-galaxy: command not found` | Ansible not installed — run `./bootstrap.sh` |
| Galaxy role not found | `ansible-galaxy install -r requirements.yml --force` |
| External SSD not mounted | Plug in the drive, or set `configure_external_storage: false` |
| `brew: command not found` | Restart the shell; Homebrew not in `PATH` yet |
| Ollama model download times out | `ollama pull <model>` manually; the playbook will pick up on re-run |
| MariaDB root password error | Ignored (`ignore_errors: true`) on re-runs |
| `nginx -t` fails | Check `brew services list`, repair config in `/opt/homebrew/etc/nginx/` |
| Grafana dashboard import 412 | Expected — dashboard already exists |
| Docker container restart-loops | `docker logs <container>` — Jellyfin / Open WebUI can restart-loop until first DB init completes |
| ERPNext first-run migration fails | Auto-retry implemented in `erpnext_post.yml`; otherwise re-run the playbook |
| Permission denied during become | Forgot `-K` / `--ask-become-pass` |

The playbook is **idempotent** — re-run it. Completed steps report `ok`, new work reports `changed`.

### Jump straight to a task

```bash
ansible-playbook main.yml -K --start-at-task="Kiwix | Pull Docker image"
ansible-playbook main.yml -K --tags "kiwix"
```

---

## Manual steps macOS cannot automate

| # | What | Why |
|---|---|---|
| 1 | `tailscale up` | Interactive browser login |
| 2 | System Settings → Keyboard → Modifier Keys → Caps Lock → Escape | Per-keyboard preference, not scriptable |
| 3 | System Settings → Privacy & Security → Full Disk Access → add Terminal / Ghostty | SIP-protected |
| 4 | Docker Desktop → Settings → Resources → Disk image location → `/Volumes/SSD1TB/docker/` | GUI-only |
| 5 | First Grafana login at `https://grafana.dev.local` | admin / your configured password |

---

## Default ports (host-visible)

| Service | Port | Domain |
|---|---|---|
| Nginx | 80 / 443 | `*.dev.local` |
| Grafana | 3000 | `grafana.dev.local` |
| Uptime Kuma | 3001 | `uptime.dev.local` |
| Gitea | 3003 (HTTP) / 2222 (SSH) | `git.dev.local` |
| GitLab | 8929 (HTTP) / 2224 (SSH) | `gitlab.dev.local` |
| Open WebUI | 3004 | `ai.dev.local` |
| Woodpecker CI | 8060 | `ci.dev.local` |
| Portainer | 9000 | `portainer.dev.local` |
| Jellyfin | 8096 | `media.dev.local` |
| n8n | 5678 | `n8n.dev.local` |
| Authentik | 9443 | `auth.dev.local` |
| Infisical | 8088 | `vault.dev.local` |
| Vaultwarden | 8087 | `pass.dev.local` |
| Outline | 3006 | `outline.dev.local` |
| HedgeDoc | 3007 | `notes.dev.local` |
| Kiwix | 8888 | `kiwix.dev.local` |
| Offline maps | 8080 | `maps.dev.local` |
| Calibre-Web | 8083 | `books.dev.local` |
| Home Assistant | 8123 | `home.dev.local` |
| Puter | 4100 | `desktop.dev.local` |
| Prometheus / Loki / Tempo / Alloy | 9090 / 3100 / 3200 / 12345 | localhost only |
| OTLP gRPC / HTTP | 4317 / 4318 | localhost only |
| Redis / MariaDB / PostgreSQL | 6379 / 3306 / 5432 | localhost only |
| dnsmasq DNS | 53 | localhost only |
| SSH | 22 | optional |

Exact ports live in `default.config.yml` — override any of them per-service.

---

## Repo layout (abridged)

```
nOS/
├── main.yml                         # entry point
├── bootstrap.sh  bootstrap/         # one-shot host preparation
├── default.config.yml               # all variables (committed)
├── default.credentials.yml          # secret templates (committed)
├── config.yml  credentials.yml      # your overrides (gitignored)
├── requirements.yml                 # Galaxy dependencies
├── roles/pazny.<service>/           # 57 roles, one per service
├── tasks/stacks/                    # core-up.yml, stack-up.yml, post-start hooks
├── tasks/                           # nginx, runtimes, macOS defaults, backup, heartbeat...
├── templates/                       # base compose stacks, Nginx vhosts
├── files/                           # static assets (Grafana dashboards, openclaw, wing)
└── docs/                            # architecture notes, fleet-architecture.md
```

See [README.md](README.md) for the full architecture, SSO/RBAC model, and per-role documentation.
