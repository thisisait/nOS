# Mac Dev Playbook — TLDR

> Ansible playbook pro kompletni setup macOS vyvojoveho prostredi na Mac Studio (Apple Silicon).
> Interní SSD 0.5 TB + externi SSD 1 TB.

---

## Co se stane automaticky

Playbook nainstaluje a nakonfiguruje **vsechno** od nuly:

| Vrstva | Co konkretne |
|--------|-------------|
| **Homebrew** | ~80 CLI nastroju + ~30 GUI aplikaci (VS Code, Docker, Brave, Ghostty...) |
| **Jazyky** | PHP 8.3 + Composer, Node.js (NVM) + npm/pnpm/yarn, Bun, Python 3.13 (pyenv), Go, .NET |
| **Web server** | Nginx s reverse proxy, HTTPS (mkcert), vhost sablony pro PHP/Node/Python/Go/static |
| **AI agent** | OpenClaw + Ollama + stazeni modelu (qwen3.5:27b) |
| **Observability** | Grafana + Prometheus + Loki + Tempo + Alloy (plny LGTM stack) |
| **IIAB sluzby** | MariaDB, WordPress, Nextcloud, Kiwix, offline mapy, n8n, Gitea, GitLab CE, Woodpecker CI, Open WebUI, Portainer, Jellyfin, Uptime Kuma, Calibre-Web |
| **Sit** | Tailscale VPN, dnsmasq (*.dev.local DNS), SSH/Samba/VNC (volitelne) |
| **Shell** | Starship prompt, fzf, zoxide, bat, eza, lazygit + aliasy v .zshrc |
| **macOS** | Finder, klavesnice, Dock, Safari, screenshot — automatizovane defaults |
| **Externi SSD** | Presmerovani dat (Kiwix, Calibre, mapy, Docker, Ollama, cache, observability) na /Volumes/SSD1TB |

---

## Prerequisites — co udelat PRED spustenim

### TL;DR — jeden prikaz misto ctyr kroku

```bash
git clone <repo-url> ~/mac-dev-playbook
cd ~/mac-dev-playbook
./bootstrap.sh
```

`bootstrap.sh` automaticky nainstaluje: **Xcode CLT → Homebrew → Ansible → Galaxy role**.

---

### Nebo rucne, krok po kroku

### 1. Xcode Command Line Tools

```bash
xcode-select --install
```

### 2. Ansible (pres Homebrew — doporuceno)

```bash
# Nejprve nainstaluj Homebrew pokud jeste neni:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"   # Apple Silicon

brew install ansible
```

### 3. Klonovat repo + Galaxy zavislosti

```bash
git clone <repo-url> ~/mac-dev-playbook
cd ~/mac-dev-playbook
ansible-galaxy install -r requirements.yml
```

### 4. Vytvorit config.yml

```bash
cp default.config.yml config.yml
```

V `config.yml` **POVINNE ZMEN**:

| Promenna | Default | Poznamka |
|----------|---------|----------|
| `mariadb_root_password` | `changeme_root` | Heslo root uzivatele MariaDB |
| `wordpress_db_password` | `changeme_wp` | Musi odpovidat `mariadb_users[0].password` |
| `nextcloud_db_password` | `changeme_nc` | Musi odpovidat `mariadb_users[1].password` |
| `nextcloud_admin_password` | `changeme_admin` | Admin ucet Nextcloud |
| `grafana_admin_password` | `changeme_grafana` | Admin ucet Grafana |
| `gitea_secret_key` | `changeme_random_32_chars` | `openssl rand -hex 32` |
| `gitea_internal_token` | `changeme_internal_tok` | `openssl rand -hex 32` |
| `vnc_password` | `""` | Nutne pouze pokud `enable_vnc: true` |

A uprav:

```yaml
# Zapni externi SSD
configure_external_storage: true
external_storage_root: "/Volumes/SSD1TB"

# Zapni IIAB sluzby, ktere chces (default: false)
install_mariadb: true
install_wordpress: true
# ...atd.
```

### 5. Externi SSD

- Pripojit disk naformatovany jako **macOS Extended (Journaled, Case-Sensitive)**
- Mount point: `/Volumes/SSD1TB` (nebo co mas v `external_storage_root`)
- Docker Desktop: rucne presunout disk image na externi SSD pres Settings → Resources → Disk image location

### 6. (Volitelne) Docker Desktop

Pokud pouzivas IIAB sluzby bezici v Dockeru (Kiwix, n8n, Uptime Kuma, Calibre-Web):
- Nainstaluj Docker Desktop (playbook ho nainstaluje pres Homebrew Cask)
- Pro externi disk: nastav disk image location pred spustenim playbooku

---

## Spusteni

```bash
cd ~/mac-dev-playbook
ansible-playbook main.yml --ask-become-pass
```

Sudo heslo je potreba pro:
- `/etc/resolver/dev.local` (dnsmasq DNS)
- SSH/Samba/VNC systemove sluzby (pokud zapnute)

### Spusteni po castech (tagy)

```bash
# Pouze observability
ansible-playbook main.yml -K --tags "observability"

# Pouze IIAB sluzby
ansible-playbook main.yml -K --tags "iiab"

# Pouze externi storage + shell
ansible-playbook main.yml -K --tags "external-storage,shell"

# Syntax check (dry run)
ansible-playbook main.yml --syntax-check
ansible-playbook main.yml -K --check
```

---

## Ocekavany vysledek

### Po uspesnem dokonceni:

```
PLAY RECAP *********************************************************************
localhost  :  ok=180  changed=95  unreachable=0  failed=0  skipped=25  rescued=0
```

- `failed=0` — vse proslo
- `skipped` — normalni (preskocene vypnute komponenty)
- `changed` — pocet novych instalaci/konfiguraci (pri prvnim spusteni vysoke)

### Overte:

```bash
# Homebrew sluzby bezi
brew services list

# DNS funguje
dig grafana.dev.local @127.0.0.1
# → 127.0.0.1

# Nginx odpovida
curl -k https://localhost

# Grafana bezi
open http://grafana.dev.local:3000
# Login: admin / <tvoje heslo>

# Ollama bezi
ollama list
# → qwen3.5:27b
```

### Soubory na externim SSD:

```
/Volumes/SSD1TB/
├── cache/              # npm, pip, composer, homebrew cache
│   ├── npm/
│   ├── pip/
│   ├── composer/
│   └── homebrew/
├── calibre/            # e-book knihovna
├── docker/             # Docker Desktop disk image (MANUAL!)
├── gitea/              # Git repozitare (Gitea)
├── gitlab/             # GitLab repozitare + data (VELKE - desitky GB)
├── openwebui/          # Open WebUI data (chat historie, RAG dokumenty)
├── woodpecker/         # Woodpecker CI data (pipeline logy, artefakty)
├── portainer/          # Portainer konfigurace
├── jellyfin/           # Jellyfin config + cache
├── media/              # Medialni knihovna (movies, shows, music)
├── kiwix/              # ZIM archivy (Wikipedia, Gutenberg...)
├── maps/               # MBTiles (offline mapy)
├── n8n/                # Workflow data
├── nextcloud-data/     # Cloud soubory
├── observability/
│   ├── prometheus/     # Metriky (30d retence)
│   ├── loki/           # Logy (31d retence)
│   └── tempo/          # Traces (7d retence)
├── ollama/
│   └── models/         # LLM modely (qwen3.5:27b ~17 GB)
├── uptime-kuma/        # Monitoring DB
└── wordpress/          # WP instalace + uploads
```

---

## Kdyz neco spadne

### Obecne pravidlo

**Playbook je idempotentni** — spust znovu a pokracuje kde skoncil.
Uz hotove kroky se preskoci (`ok`), nove se aplikuji (`changed`).

```bash
# Proste spust znovu
ansible-playbook main.yml -K
```

### Casté problemy

| Problem | Reseni |
|---------|--------|
| `ansible-galaxy: command not found` | Ansible neni nainstalovan — spust `./bootstrap.sh` |
| `Galaxy role not found` | `ansible-galaxy install -r requirements.yml --force` |
| `External SSD not mounted` | Pripoj disk, nebo `configure_external_storage: false` |
| `brew: command not found` | Restart terminal, Homebrew neni v PATH |
| `Ollama model download timeout` | `ollama pull qwen3.5:27b` rucne (30-60 min) |
| `MariaDB root password error` | Ignorovano (`ignore_errors: true`), bezpecne pri re-runu |
| `nginx -t fails` | Zkontroluj `brew services list`, oprav config v `/opt/homebrew/etc/nginx/` |
| `Grafana dashboard import 412` | Ocekavane — dashboard uz existuje |
| `Docker container fails` | `docker ps -a`, zkontroluj logy: `docker logs <container>` |
| `Permission denied (become)` | Spoustis s `-K` / `--ask-become-pass`? |
| `PHP socket not found` | Spust `brew services restart php@8.3` pred nginx |

### Spusteni jednoho konkretniho tasku

```bash
# Zacni od urciteho tasku (preskoci predchozi)
ansible-playbook main.yml -K --start-at-task="[Kiwix] Pull Docker image"

# Pouze jeden tag
ansible-playbook main.yml -K --tags "kiwix"
```

---

## Po dokonceni — manualni kroky

| # | Co | Proc |
|---|-----|------|
| 1 | `tailscale up` | Prihlaseni do VPN (otevre prohlizec) |
| 2 | Docker Desktop → disk image location | Presun na SSD (pokud jeste ne) |
| 3 | System Settings → Privacy → Full Disk Access | Pridat Terminal/Ghostty (SIP chranene) |
| 4 | System Settings → Keyboard → Modifier Keys | Caps Lock → Esc (per-keyboard, nelze automatizovat) |
| 5 | Login do Grafana | `https://grafana.dev.local` — admin / heslo |
| 6 | `brew services list` | Overit ze vsechny sluzby bezi |

---

## Architektura portů

| Sluzba | Port | Domena |
|--------|------|--------|
| Nginx | 80/443 | *.dev.local |
| Grafana | 3000 | grafana.dev.local |
| Uptime Kuma | 3001 | uptime.dev.local |
| Gitea | 3003 | git.dev.local |
| Gitea SSH | 2222 | — |
| GitLab | 8929 | gitlab.dev.local |
| GitLab SSH | 2224 | — |
| Open WebUI | 3004 | ai.dev.local |
| Woodpecker CI | 8060 | ci.dev.local |
| Portainer | 9000 | portainer.dev.local |
| Jellyfin | 8096 | media.dev.local |
| n8n | 5678 | n8n.dev.local |
| WordPress | — | wordpress.dev.local |
| Nextcloud | — | cloud.dev.local |
| Kiwix | 8888 | kiwix.dev.local |
| Maps | 8080 | maps.dev.local |
| Calibre-Web | 8083 | books.dev.local |
| Prometheus | 9090 | localhost only |
| Loki | 3100 | localhost only |
| Tempo | 3200 | localhost only |
| Alloy UI | 12345 | localhost only |
| Alloy OTLP gRPC | 4317 | localhost only |
| Alloy OTLP HTTP | 4318 | localhost only |
| Redis | 6379 | localhost only |
| MariaDB | 3306 | localhost only |
| dnsmasq DNS | 53 | localhost only |
| SSH | 22 | (volitelne) |

---

## Struktura repozitare

```
mac-dev-playbook/
├── main.yml                      # Hlavni playbook (handlers, roles, task imports)
├── default.config.yml            # Vychozi konfigurace (NEKOPIRUJ — pouzij config.yml)
├── config.yml                    # TVA konfigurace (gitignored, override)
├── requirements.yml              # Ansible Galaxy zavislosti
├── tasks/
│   ├── external-storage.yml      # Externi SSD setup + set_fact override
│   ├── nginx.yml                 # Nginx + mkcert + vhosts
│   ├── php.yml                   # PHP + Composer
│   ├── node.yml                  # Node.js + NVM
│   ├── python.yml                # Python + pyenv
│   ├── golang.yml                # Go
│   ├── dotnet.yml                # .NET
│   ├── bun.yml                   # Bun runtime
│   ├── openclaw.yml              # OpenClaw AI agent + Ollama
│   ├── observability.yml         # Grafana LGTM stack
│   ├── shell-extras.yml          # Starship, fzf, zoxide, aliasy
│   ├── tailscale.yml             # VPN
│   ├── dnsmasq.yml               # DNS
│   ├── macos-defaults.yml        # macOS system preferences
│   ├── system-services.yml       # SSH, Samba, VNC
│   └── iiab/
│       ├── mariadb.yml           # MariaDB databaze
│       ├── wordpress.yml         # WordPress CMS
│       ├── nextcloud.yml         # Nextcloud cloud
│       ├── kiwix.yml             # Offline Wikipedia (Docker)
│       ├── maps.yml              # Offline mapy (tileserver-gl)
│       ├── n8n.yml               # Workflow automation (Docker)
│       ├── gitea.yml             # Git server
│       ├── uptime-kuma.yml       # Monitoring (Docker)
│       └── calibreweb.yml        # E-book server (Docker)
├── files/
│   ├── nginx/                    # Nginx configs (template-processed)
│   ├── observability/            # Grafana/Prometheus/Loki/Tempo/Alloy configs
│   └── openclaw/                 # AI agent configs
└── templates/                    # Jinja2 sablony
```
