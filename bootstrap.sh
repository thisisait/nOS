#!/bin/bash
# bootstrap.sh — spustit JEDNOU pred prvnim ansible-playbook main.yml
# Nainstaluje: Xcode CLT → Homebrew → Ansible → Galaxy role/kolekce

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# ── 1. Xcode Command Line Tools ──────────────────────────────────────────────
step "Xcode Command Line Tools"
if xcode-select -p &>/dev/null; then
    ok "Xcode CLT already installed ($(xcode-select -p))"
else
    echo "Spoustim installer — potvrdte v dialogovem okne..."
    xcode-select --install
    echo "Cekam na dokonceni instalace Xcode CLT..."
    until xcode-select -p &>/dev/null; do sleep 5; done
    ok "Xcode CLT installed"
fi

# ── 2. Homebrew ───────────────────────────────────────────────────────────────
step "Homebrew"
if command -v brew &>/dev/null; then
    ok "Homebrew already installed ($(brew --version | head -1))"
else
    echo "Instaluji Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Pridej Homebrew do PATH pro zbytek tohoto skriptu (Apple Silicon)
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    ok "Homebrew installed"
fi

# Zajisti ze brew je v PATH
if ! command -v brew &>/dev/null; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# ── 3. Ansible ────────────────────────────────────────────────────────────────
step "Ansible"
if command -v ansible &>/dev/null; then
    ok "Ansible already installed ($(ansible --version | head -1))"
else
    echo "Instaluji Ansible pres Homebrew..."
    brew install ansible
    ok "Ansible installed"
fi

# ── 4. Galaxy role a kolekce ──────────────────────────────────────────────────
step "Ansible Galaxy role & kolekce (requirements.yml)"
ansible-galaxy install -r requirements.yml
ok "Galaxy dependencies installed"

# ── Hotovo ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║  Bootstrap dokoncen! Dalsi kroky:                   ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  1. cp default.config.yml config.yml"
echo "  2. Uprav config.yml (hesla, zapni/vypni komponenty)"
echo "  3. ansible-playbook main.yml --ask-become-pass"
echo ""
warn "Nezapomen: vsechna 'changeme_*' hesla v config.yml POVINNE zmen!"
echo ""
