#!/usr/bin/env zsh
# ==============================================================================
# Inspektor Klepitko – Onboarding Script
# Run after the Ansible playbook finishes to initialize the agentic environment
#
# Usage: ~/agents/onboard.sh
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
echo -e "${BOLD}🦞 Inspektor Klepitko – Onboarding${RESET}"
sep

# ── 1. Directory structure ────────────────────────────────────────────────────

log "Creating directory structure..."
mkdir -p "${AGENTS_DIR}"
mkdir -p "${PROJECTS_DIR}/default"
mkdir -p "${LOG_DIR}"
mkdir -p "${OPENCLAW_CONFIG}/memory"
ok "Directories ready"

# ── 2. Dependency check ───────────────────────────────────────────────────────

sep
log "Checking dependencies..."

check_cmd() {
  if command -v "$1" &>/dev/null; then
    ok "$1 → $(command -v $1)"
  else
    warn "$1 → NOT FOUND (check the installation)"
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
log "Checking Ollama model..."

OLLAMA_MODEL="${OPENCLAW_MODEL:-qwen3.5:27b}"

if ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
  ok "Model ${OLLAMA_MODEL} is available"
else
  warn "Model ${OLLAMA_MODEL} is not downloaded. Pulling..."
  ollama pull "${OLLAMA_MODEL}" && ok "Model pulled" || fail "Pull failed"
fi

# ── 4. Nginx check ────────────────────────────────────────────────────────────

sep
log "Checking nginx..."

if "${HOMEBREW_PREFIX}/bin/nginx" -t 2>/dev/null; then
  ok "Nginx configuration is valid"
else
  fail "Nginx configuration has errors! Run: nginx -t"
fi

if brew services list | grep nginx | grep -q started; then
  ok "Nginx is running"
else
  warn "Nginx is not running. Starting..."
  brew services start nginx && ok "Nginx started" || fail "Failed to start Nginx"
fi

# ── 5. PHP-FPM check ──────────────────────────────────────────────────────────

sep
log "Checking PHP-FPM..."

if brew services list | grep php | grep -q started; then
  ok "PHP-FPM is running"
  PHP_VERSION=$(php -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;' 2>/dev/null || echo "?")
  ok "PHP version: ${PHP_VERSION}"
else
  warn "PHP-FPM is not running. Starting..."
  brew services start php 2>/dev/null || warn "Failed to start PHP-FPM"
fi

# ── 6. OpenClaw configuration ─────────────────────────────────────────────────

sep
log "Checking OpenClaw configuration..."

if [[ -f "${OPENCLAW_CONFIG}/openclaw.json" ]]; then
  ok "openclaw.json found"
else
  warn "openclaw.json not found in ${OPENCLAW_CONFIG}"
fi

if [[ -f "${OPENCLAW_CONFIG}/SOUL.md" ]]; then
  ok "SOUL.md (Inspektor Klepitko persona) found"
else
  warn "SOUL.md not found – the agent will lack context"
fi

# ── 7. Create initialization log ──────────────────────────────────────────────

sep
log "Creating initialization log..."

INIT_DATE=$(date '+%Y-%m-%d')
INIT_TIME=$(date '+%H:%M')
INIT_LOG="${LOG_DIR}/${INIT_DATE}_TASK-000_system-onboarding.md"

if [[ ! -f "${INIT_LOG}" ]]; then
  cat > "${INIT_LOG}" << EOF
---
date: ${INIT_DATE} ${INIT_TIME}
agent: Inspektor Klepitko
task_id: TASK-000
status: COMPLETE
priority: HIGH
tags: [onboarding, system, init]
---

# TASK-000: Initialize the agentic environment

## Goal
Start and verify the entire Mac Studio server infrastructure.
Prepare the environment for agentic DevOps operations.

## Sub-agents
- [x] **OnboardScript:** Automatic system verification

## Server configuration

| Parameter | Value |
|-----------|-------|
| OS | $(sw_vers -productName 2>/dev/null || echo macOS) $(sw_vers -productVersion 2>/dev/null || echo ?) |
| Arch | $(uname -m) |
| Homebrew | ${HOMEBREW_PREFIX} |
| Nginx | $(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo ?) |
| PHP | $(php -r 'echo PHP_VERSION;' 2>/dev/null || echo ?) |
| Node.js | $(node --version 2>/dev/null || echo ?) |
| Go | $(go version 2>/dev/null | awk '{print \$3}' || echo ?) |
| Ollama model | ${OLLAMA_MODEL} |

## Directories

\`\`\`
~/
├── agents/          ← OpenClaw, agent configuration
│   ├── log/         ← Structured logs of agentic work
│   └── onboard.sh   ← This script
└── projects/        ← Web projects (nginx webroot)
    └── default/     ← Default landing page
\`\`\`

## Nginx vhost templates

\`\`\`
${NGINX_CONF}/sites-available/
├── default.conf        ← Active – catch-all localhost
├── php-app.conf        ← Template for PHP projects
├── node-proxy.conf     ← Template for Node.js
├── python-proxy.conf   ← Template for Python/FastAPI
├── go-proxy.conf       ← Template for Go
└── static-site.conf    ← Template for static sites
\`\`\`

## Result
System initialized. Inspektor Klepitko is ready to accept tasks.

## Notes
- Add a project: copy into ~/projects/<name>/ + configure an nginx vhost
- SSL: \`mkcert -cert-file ... -key-file ... "*.dev.local"\`
- Start the agent: \`openclaw start\`
EOF
  ok "Initialization log saved: ${INIT_LOG}"
else
  ok "Initialization log already exists: ${INIT_LOG}"
fi

# ── 8. Summary ────────────────────────────────────────────────────────────────

sep
echo -e "${BOLD}🦞 Inspektor Klepitko is ready!${RESET}"
sep
echo ""
echo -e "  ${BOLD}Start the agent:${RESET}"
echo -e "    openclaw start"
echo ""
echo -e "  ${BOLD}New project (example):${RESET}"
echo -e "    mkdir -p ~/projects/my-project"
echo -e "    cp ${NGINX_CONF}/sites-available/php-app.conf \\"
echo -e "       ${NGINX_CONF}/sites-available/my-project.conf"
echo -e "    # edit server_name and root in my-project.conf"
echo -e "    ln -sf ${NGINX_CONF}/sites-available/my-project.conf \\"
echo -e "           ${NGINX_CONF}/sites-enabled/"
echo -e "    nginx -t && brew services restart nginx"
echo ""
echo -e "  ${BOLD}Agent logs:${RESET}"
echo -e "    ls -la ${LOG_DIR}/"
echo ""
sep
