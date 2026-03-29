#!/usr/bin/env zsh
# ==============================================================================
# Inspektor Klepítko – Onboarding Script
# Spusť po dokončení Ansible playbooku pro inicializaci agentického prostředí
#
# Použití: ~/agents/onboard.sh
# ==============================================================================

set -euo pipefail

BOLD='\033[1m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

AGENTS_DIR=~/agents
PROJECTS_DIR=~/projects
LOG_DIR=~/agents/log
OPENCLAW_CONFIG=~/.openclaw
HOMEBREW_PREFIX="${HOMEBREW_PREFIX:-/opt/homebrew}"
NGINX_CONF="${HOMEBREW_PREFIX}/etc/nginx"

log()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
fail() { echo -e "${RED}[FAIL]${RESET}  $*"; }
sep()  { echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"; }

sep
echo -e "${BOLD}🦞 Inspektor Klepítko – Onboarding${RESET}"
sep

# ── 1. Adresářová struktura ────────────────────────────────────────────────────

log "Vytvářím adresářovou strukturu..."
mkdir -p "${AGENTS_DIR}"
mkdir -p "${PROJECTS_DIR}/default"
mkdir -p "${LOG_DIR}"
mkdir -p "${OPENCLAW_CONFIG}/memory"
ok "Adresáře připraveny"

# ── 2. Kontrola závislostí ────────────────────────────────────────────────────

sep
log "Kontrola závislostí..."

check_cmd() {
  if command -v "$1" &>/dev/null; then
    ok "$1 → $(command -v $1)"
  else
    warn "$1 → NENALEZENO (zkontroluj instalaci)"
  fi
}

check_cmd nginx
check_cmd php
check_cmd node
check_cmd bun
check_cmd python3
check_cmd go
check_cmd dotnet
check_cmd ollama
check_cmd openclaw

# ── 3. Ollama model ───────────────────────────────────────────────────────────

sep
log "Kontrola Ollama modelu..."

OLLAMA_MODEL="${OPENCLAW_MODEL:-qwen3.5:27b}"

if ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
  ok "Model ${OLLAMA_MODEL} je k dispozici"
else
  warn "Model ${OLLAMA_MODEL} není stažen. Stahuji..."
  ollama pull "${OLLAMA_MODEL}" && ok "Model stažen" || fail "Stahování selhalo"
fi

# ── 4. Nginx kontrola ─────────────────────────────────────────────────────────

sep
log "Kontrola nginx..."

if "${HOMEBREW_PREFIX}/bin/nginx" -t 2>/dev/null; then
  ok "Nginx konfigurace je validní"
else
  fail "Nginx konfigurace má chyby! Spusť: nginx -t"
fi

if brew services list | grep nginx | grep -q started; then
  ok "Nginx běží"
else
  warn "Nginx neběží. Spouštím..."
  brew services start nginx && ok "Nginx spuštěn" || fail "Nginx se nepodařilo spustit"
fi

# ── 5. PHP-FPM kontrola ───────────────────────────────────────────────────────

sep
log "Kontrola PHP-FPM..."

if brew services list | grep php | grep -q started; then
  ok "PHP-FPM běží"
  PHP_VERSION=$(php -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;' 2>/dev/null || echo "?")
  ok "PHP verze: ${PHP_VERSION}"
else
  warn "PHP-FPM neběží. Spouštím..."
  brew services start php 2>/dev/null || warn "Nedaří se spustit PHP-FPM"
fi

# ── 6. OpenClaw konfigurace ───────────────────────────────────────────────────

sep
log "Kontrola OpenClaw konfigurace..."

if [[ -f "${OPENCLAW_CONFIG}/openclaw.json" ]]; then
  ok "openclaw.json nalezen"
else
  warn "openclaw.json nenalezen v ${OPENCLAW_CONFIG}"
fi

if [[ -f "${OPENCLAW_CONFIG}/SOUL.md" ]]; then
  ok "SOUL.md (Inspektor Klepítko persona) nalezen"
else
  warn "SOUL.md nenalezen – agent nebude mít kontext"
fi

# ── 7. Vytvoření inicializačního logu ─────────────────────────────────────────

sep
log "Vytvářím inicializační log..."

INIT_DATE=$(date '+%Y-%m-%d')
INIT_TIME=$(date '+%H:%M')
INIT_LOG="${LOG_DIR}/${INIT_DATE}_TASK-000_system-onboarding.md"

if [[ ! -f "${INIT_LOG}" ]]; then
  cat > "${INIT_LOG}" << EOF
---
date: ${INIT_DATE} ${INIT_TIME}
agent: Inspektor Klepítko
task_id: TASK-000
status: COMPLETE
priority: HIGH
tags: [onboarding, system, init]
---

# TASK-000: Inicializace agentického prostředí

## Cíl
Spustit a ověřit veškerou infrastrukturu Mac Studio serveru.
Připravit prostředí pro agentic DevOps operace.

## Sub-agenti
- [x] **OnboardScript:** Automatická verifikace systému

## Konfigurace serveru

| Parametr | Hodnota |
|----------|---------|
| OS | $(sw_vers -productName 2>/dev/null || echo macOS) $(sw_vers -productVersion 2>/dev/null || echo ?) |
| Arch | $(uname -m) |
| Homebrew | ${HOMEBREW_PREFIX} |
| Nginx | $(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo ?) |
| PHP | $(php -r 'echo PHP_VERSION;' 2>/dev/null || echo ?) |
| Node.js | $(node --version 2>/dev/null || echo ?) |
| Go | $(go version 2>/dev/null | awk '{print \$3}' || echo ?) |
| Ollama model | ${OLLAMA_MODEL} |

## Adresáře

\`\`\`
~/
├── agents/          ← OpenClaw, konfigurace agentů
│   ├── log/         ← Strukturované logy agentické práce
│   └── onboard.sh   ← Tento script
└── projects/        ← Webové projekty (nginx webroot)
    └── default/     ← Výchozí landing page
\`\`\`

## Nginx vhost šablony

\`\`\`
${NGINX_CONF}/sites-available/
├── default.conf        ← Aktivní – catch-all localhost
├── php-app.conf        ← Šablona pro PHP projekty
├── node-proxy.conf     ← Šablona pro Node.js
├── python-proxy.conf   ← Šablona pro Python/FastAPI
├── go-proxy.conf       ← Šablona pro Go
└── static-site.conf    ← Šablona pro statické stránky
\`\`\`

## Výsledek
Systém inicializován. Inspektor Klepítko je připraven přijímat úkoly.

## Poznámky
- Přidej projekt: zkopíruj do ~/projects/<název>/ + nastav nginx vhost
- SSL: \`mkcert -cert-file ... -key-file ... "*.dev.local"\`
- Spuštění agenta: \`openclaw start\`
EOF
  ok "Inicializační log uložen: ${INIT_LOG}"
else
  ok "Inicializační log již existuje: ${INIT_LOG}"
fi

# ── 8. Souhrn ─────────────────────────────────────────────────────────────────

sep
echo -e "${BOLD}🦞 Inspektor Klepítko je připraven!${RESET}"
sep
echo ""
echo -e "  ${BOLD}Spuštění agenta:${RESET}"
echo -e "    openclaw start"
echo ""
echo -e "  ${BOLD}Nový projekt (příklad):${RESET}"
echo -e "    mkdir -p ~/projects/muj-projekt"
echo -e "    cp ${NGINX_CONF}/sites-available/php-app.conf \\"
echo -e "       ${NGINX_CONF}/sites-available/muj-projekt.conf"
echo -e "    # uprav server_name a root v muj-projekt.conf"
echo -e "    ln -sf ${NGINX_CONF}/sites-available/muj-projekt.conf \\"
echo -e "           ${NGINX_CONF}/sites-enabled/"
echo -e "    nginx -t && brew services restart nginx"
echo ""
echo -e "  ${BOLD}Logy agenta:${RESET}"
echo -e "    ls -la ${LOG_DIR}/"
echo ""
sep
