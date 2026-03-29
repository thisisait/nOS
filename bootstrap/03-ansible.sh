#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Krok 3: Ansible                                                             │
# │                                                                             │
# │ Co dělá:  Nainstaluje Ansible přes Homebrew.                                │
# │ Proč:     Ansible je engine který spouští playbook.                         │
# │ Jak long: ~1-2 minuty.                                                      │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

# Zajisti že brew je v PATH (Apple Silicon)
if ! command -v brew &>/dev/null && [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

step "Ansible"

if command -v ansible &>/dev/null; then
  ok "Ansible je nainstalováno ($(ansible --version | head -1))"
  exit 0
fi

echo "Instaluji Ansible přes Homebrew..."
brew install ansible

ok "Ansible nainstalováno"
