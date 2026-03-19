# Mac Dev Playbook – Pazny Edition

Ansible playbook pro automatizaci macOS vývojového prostředí na **Mac Studio (Apple Silicon, 36 GB RAM)**. Vychází z projektu [geerlingguy/mac-dev-playbook](https://github.com/geerlingguy/mac-dev-playbook) a rozšiřuje ho o self-hosted AI agenta, plný observability stack a offline knowledge services.

---

## Obsah

- [Co playbook nainstaluje](#co-playbook-nainstaluje)
- [Rychlý start](#rychlý-start)
- [Konfigurace – INSTALLATION QUEUE](#konfigurace--installation-queue)
- [Přizpůsobení](#přizpůsobení)
- [Adresářová struktura](#adresářová-struktura)
- [Dostupné tagy](#dostupné-tagy)
- [Manuální kroky po instalaci](#manuální-kroky-po-instalaci)
- [Struktura repozitáře](#struktura-repozitáře)

---

## Co playbook nainstaluje

### Vývojová prostředí

| Stack | Nástroj | Správce verzí |
|-------|---------|---------------|
| PHP 8.3 + FPM | Composer, rozšíření | Homebrew `php@8.3` |
| Node.js LTS | yarn, pnpm, TypeScript, pm2 | NVM |
| Bun | globální balíčky | curl installer |
| Python 3.13 | FastAPI, LangChain, JupyterLab, numpy, … | pyenv |
| Go (latest) | gopls, air, golangci-lint | Homebrew |
| .NET (C#) | EF CLI, dotnet-script | Homebrew Cask |

### Web server

**Nginx** s plnou konfigurací:
- Sites-available / sites-enabled vzor (symlinky)
- Šablony vhostů pro PHP, Node.js, Python, Go, .NET, statické soubory
- mkcert lokální SSL certifikáty (`*.dev.local`)
- gzip, rate limiting, proxy cache

### Moderní CLI nástroje

| Nástroj | Nahrazuje | Popis |
|---------|-----------|-------|
| `ripgrep` (`rg`) | grep | Rychlejší grep, `.gitignore`-aware |
| `fd` | find | Rychlejší a přehlednější find |
| `bat` | cat | Syntax highlighting + git diff |
| `eza` | ls | Ikonky, stromové zobrazení, git status |
| `fzf` | — | Fuzzy finder (Ctrl+R, Ctrl+T) |
| `zoxide` (`z`) | cd | Chytré cd s váhováním historie |
| `lazygit` (`lg`) | git | TUI pro celý git workflow |
| `starship` | prompt | GPU-fast cross-shell prompt |
| `ncdu` | du | Interaktivní disk usage TUI |
| `duf` | df | Přehledný diskový panel |

### AI Agent – Inspektor Klepítko

Self-hosted AI agent bez API klíče:

- **Ollama** – lokální LLM inference (model `qwen3.5:27b`, optimální pro 36 GB RAM)
- **OpenClaw** – agentic framework instalovaný přes `ollama launch openclaw`
- Agent běží jako **launchd daemon** (vždy zapnutý, autorestart)
- Persona: **DevOps Lead Engineer** s přehledem o celé konfiguraci serveru
- 6 sub-agentů: CodeAgent, InfraAgent, DeployAgent, SecurityAgent, MonitorAgent, DataAgent

Cesty:
```
~/pazny/agents/          # konfigurace agentů
~/pazny/projects/        # projekty hostované přes nginx
~/pazny/agents/log/      # strukturované .md logy agentické práce
```

### Observability – LGTM Stack

Plně nakonfigurovaný monitoring stack (Grafana Alloy jako unified collector):

```
Alloy → Prometheus  (metriky: CPU, RAM, nginx, PHP-FPM, Redis)
     → Loki        (logy: nginx access/error, agent logy)
     → Tempo       (traces: OTLP gRPC :4317, HTTP :4318)
           ↓
        Grafana    (dashboardy, datasources auto-provisioned)
```

| Služba | URL | Port |
|--------|-----|------|
| Grafana | `https://grafana.dev.local` | 3000 |
| Prometheus | `http://localhost:9090` | 9090 |
| Loki | `http://localhost:3100` | 3100 |
| Tempo | `http://localhost:3200` | 3200 |
| Alloy UI | `http://localhost:12345` | 12345 |

Community dashboardy se automaticky stáhnou a importují (Node Exporter Full, macOS Overview, Nginx, PHP-FPM, Loki, Tempo).

### IIAB – Self-hosted Knowledge & Productivity Services

Všechny služby jsou volitelné (`false` v INSTALLATION QUEUE), dostupné přes nginx na `.dev.local` doménách:

| Služba | Doména | Stack | Popis |
|--------|--------|-------|-------|
| WordPress | `wordpress.dev.local` | PHP-FPM + MariaDB | CMS |
| Nextcloud | `cloud.dev.local` | PHP-FPM + MariaDB | Self-hosted cloud |
| Kiwix | `kiwix.dev.local` | Docker | Offline Wikipedia, Gutenberg, ZIM |
| Offline Mapy | `maps.dev.local` | tileserver-gl | MBTiles offline mapy |
| n8n | `n8n.dev.local` | Docker | Workflow automation |
| Gitea | `gitea.dev.local` | Homebrew | Self-hosted Git |
| Uptime Kuma | `uptime.dev.local` | Docker | Monitoring / status page |
| Calibre-Web | `books.dev.local` | Docker | E-book knihovna |

### GUI Aplikace (Homebrew Cask)

Editory, terminály, prohlížeče, nástroje a kreativní software nainstalovaný přes Homebrew Cask:

<details>
<summary>Zobrazit kompletní seznam</summary>

**Editory / IDE:** VS Code, Windsurf (Codeium AI IDE), Sublime Text
**Terminály:** Ghostty (GPU-accelerated), iTerm2
**Prohlížeče:** Brave, Chrome, Firefox
**Produktivita:** Raycast (Spotlight replacement)
**Komunikace:** Slack, Discord
**Databáze:** Sequel Ace, TablePlus
**API / Dev tools:** Insomnia, balenaEtcher, LiCEcap
**Bezpečnost:** LastPass, OpenVPN Connect
**Média:** VLC, Spotify, HandBrake
**Kreativní:** Blender, FL Studio
**Observability:** Obsidian (propojení s `~/pazny/agents/log/`)
**Systém:** Dropbox, Ice (menu bar), Stats (systémové metriky v menu baru)

</details>

---

## Rychlý start

### 1. Předpoklady

```bash
# Xcode command line tools
xcode-select --install

# Python do $PATH (pro Ansible)
export PATH="$HOME/Library/Python/3.x/bin:/opt/homebrew/bin:$PATH"

# Ansible
pip3 install ansible
```

### 2. Klonování a instalace rolí

```bash
git clone <tento-repozitar> ~/mac-dev-playbook
cd ~/mac-dev-playbook
ansible-galaxy install -r requirements.yml
```

### 3. Přizpůsobení

```bash
cp default.config.yml config.yml
# Uprav config.yml dle potřeby (viz sekce níže)
```

> **Důležité:** Hesla v `config.yml` jsou výchozí placeholder hodnoty. Před spuštěním přepiš všechna `changeme_*` hesla.

### 4. Spuštění

```bash
# Plná instalace
ansible-playbook main.yml --ask-become-pass

# Pouze konkrétní část (např. jen observability)
ansible-playbook main.yml -K --tags "observability"

# Suché spuštění (bez změn, jen výpis co by se stalo)
ansible-playbook main.yml -K --check
```

---

## Konfigurace – INSTALLATION QUEUE

Hlavní konfigurační soubor je **`default.config.yml`**. Začátek souboru obsahuje přehledný přepínač komponent:

```yaml
# INSTALLATION QUEUE – zakomentuj řádek pro přeskočení komponenty

install_homebrew_packages: true   # CLI nástroje
install_nginx: true               # Nginx
install_php: true                 # PHP 8.x + FPM
install_node: true                # Node.js + NVM
install_bun: true                 # Bun runtime
install_python: true              # Python + pyenv
install_golang: true              # Go
install_dotnet: true              # .NET / C#
install_openclaw: true            # AI Agent (Ollama)
install_shell_extras: true        # Starship prompt + aliasy
configure_macos_defaults: true    # macOS nastavení (Finder, klávesnice, Dock…)

enable_ssh: false                 # SSH server
enable_samba: false               # SMB sdílení souborů
enable_vnc: false                 # Sdílení obrazovky

install_observability: true       # Grafana + Prometheus + Loki + Tempo + Alloy

# IIAB – self-hosted services (vše false = výchozí)
install_mariadb: false
install_wordpress: false
install_nextcloud: false
install_kiwix: false
install_offline_maps: false
install_n8n: false
install_gitea: false
install_uptime_kuma: false
install_calibreweb: false
```

---

## Přizpůsobení

Vytvoř soubor `config.yml` (přepisuje `default.config.yml`) a uprav jen to, co potřebuješ:

```yaml
# config.yml – přepiš výchozí hodnoty

# Uživatelské cesty
openclaw_user: "tvujuzivatel"
openclaw_base_dir: "/Users/tvujuzivatel"

# Bezpečnostní hesla – VŽDY PŘEPIŠ!
mariadb_root_password: "silne-heslo"
grafana_admin_password: "silne-heslo"
wordpress_db_password: "silne-heslo"
nextcloud_admin_password: "silne-heslo"
gitea_secret_key: "nahodny-string-32-znaku"

# Ollama model (závisí na RAM)
# 36 GB RAM: qwen3.5:27b (doporučeno)
# 16 GB RAM: qwen3.5:14b
# 64 GB RAM: llama3.3:70b
openclaw_model: "qwen3.5:27b"

# Vlastní dotfiles
dotfiles_repo: "https://github.com/tvujuzivatel/dotfiles.git"

# Přidat vlastní npm balíčky
node_global_packages:
  - yarn
  - pnpm
  - typescript
  - vue-cli          # vlastní přidání

# Přidat vlastní pip balíčky
pip_packages:
  - name: fastapi
  - name: httpx
  - name: mujprojekt  # vlastní přidání
```

---

## Adresářová struktura

```
~/pazny/
├── agents/
│   ├── log/          # .md logy agentické práce (YYYY-MM-DD_TASK-NNN_popis.md)
│   └── ...           # OpenClaw konfigurace
├── projects/         # Projekty hostované přes nginx
│   └── default/      # Výchozí landing page
├── observability/
│   ├── dashboards/   # Stažené Grafana dashboardy (JSON)
│   ├── prometheus/   # Prometheus data
│   ├── loki/         # Loki data
│   └── tempo/        # Tempo data
├── kiwix/            # ZIM soubory (offline Wikipedia, Gutenberg…)
├── maps/             # MBTiles soubory (offline mapy)
├── gitea/            # Gitea data + repozitáře
├── n8n/              # n8n data + workflow
├── calibre-web/      # Calibre knihovna + config
└── uptime-kuma/      # Uptime Kuma data
```

---

## Dostupné tagy

Spusť pouze konkrétní část playbooku pomocí `--tags`:

```bash
ansible-playbook main.yml -K --tags "TAG"
```

| Tag | Co spustí |
|-----|-----------|
| `homebrew` | Homebrew balíčky a cask apps |
| `nginx` | Nginx instalace a konfigurace |
| `php` | PHP + PHP-FPM |
| `node` | Node.js + NVM |
| `python` | Python + pyenv |
| `go` | Go jazyk |
| `dotnet` | .NET SDK |
| `openclaw` | AI Agent (Ollama + OpenClaw) |
| `shell-extras` | Starship prompt + aliasy |
| `observability` | Celý LGTM stack |
| `grafana` | Pouze Grafana |
| `macos-defaults` | macOS systémová nastavení |
| `system-services` | SSH, Samba, VNC |
| `tailscale` | Tailscale VPN |
| `dnsmasq` | Lokální DNS pro *.dev.local |
| `iiab` | Všechny IIAB služby |
| `n8n` | n8n workflow automation |
| `gitea` | Gitea Git server |

---

## Manuální kroky po instalaci

Některé nastavení macOS nelze plně automatizovat (SIP, HW-specifické nastavení):

1. **Caps Lock → Escape** – System Settings → Keyboard → Modifier Keys → nastavit pro každou klávesnici zvlášť
2. **Full Disk Access pro Terminal** – System Settings → Privacy & Security → Full Disk Access → přidat Terminal / Ghostty
3. **VNC heslo** – pokud `enable_vnc: true`, nastav `vnc_password` v `config.yml` před spuštěním
4. **Tailscale login** – po instalaci otevři aplikaci Tailscale a přihlas se na https://login.tailscale.com

> **mkcert a `.dev.local` DNS jsou automatizovány** – mkcert CA se nainstaluje do systému automaticky a dnsmasq zajistí přeložení všech `*.dev.local` domén na `127.0.0.1` bez zásahu do `/etc/hosts`.

---

## Struktura repozitáře

```
mac-dev-playbook/
├── main.yml                      # Hlavní playbook (handlers + task imports)
├── default.config.yml            # Výchozí konfigurace (INSTALLATION QUEUE zde)
├── requirements.yml              # Ansible Galaxy role závislosti
├── inventory                     # Ansible inventory (localhost)
│
├── tasks/
│   ├── nginx.yml                 # Nginx + vhosts deployment
│   ├── php.yml                   # PHP-FPM + konfigurace
│   ├── node.yml                  # Node.js + NVM
│   ├── bun.yml                   # Bun runtime
│   ├── python.yml                # pyenv + pip
│   ├── golang.yml                # Go toolchain
│   ├── dotnet.yml                # .NET SDK
│   ├── openclaw.yml              # Ollama + OpenClaw + agent setup
│   ├── shell-extras.yml          # Starship + zoxide + fzf + aliasy
│   ├── observability.yml         # Grafana LGTM stack
│   ├── macos-defaults.yml        # macOS system preferences
│   ├── system-services.yml       # SSH, Samba, VNC
│   └── iiab/
│       ├── mariadb.yml
│       ├── wordpress.yml
│       ├── nextcloud.yml
│       ├── kiwix.yml
│       ├── maps.yml
│       ├── n8n.yml
│       ├── gitea.yml
│       ├── uptime-kuma.yml
│       └── calibreweb.yml
│
├── files/
│   ├── nginx/
│   │   ├── nginx.conf            # Hlavní nginx config (kqueue, gzip, TLS, rate limiting)
│   │   └── sites-available/      # Vhost šablony (php-app, node, python, go, grafana, n8n…)
│   ├── observability/
│   │   ├── alloy/config.alloy.j2     # Grafana Alloy pipeline (metrics+logs+traces)
│   │   ├── grafana/provisioning/     # Auto-provisioning datasources + dashboards
│   │   ├── prometheus/               # Prometheus scrape config
│   │   ├── loki/                     # Loki storage config
│   │   └── tempo/                    # Tempo tracing config
│   ├── openclaw/
│   │   ├── openclaw.json.j2          # OpenClaw config (Ollama backend)
│   │   ├── SOUL.md                   # Inspektor Klepítko persona + znalost serveru
│   │   ├── AGENTS.md                 # Sub-agenti a jejich role
│   │   ├── TOOLS.md                  # Dostupné nástroje
│   │   └── onboard.sh                # Onboarding skript agenta
│   └── starship.toml.j2              # Starship prompt konfigurace
│
└── full-mac-setup.md             # Průvodce instalací od nuly (Jeff Geerling)
```

---

## Původ projektu

Tento playbook vznikl fork-em z [geerlingguy/mac-dev-playbook](https://github.com/geerlingguy/mac-dev-playbook) od [Jeffa Geerlinga](https://www.jeffgeerling.com/), autora knihy [Ansible for DevOps](https://www.ansiblefordevops.com/).
