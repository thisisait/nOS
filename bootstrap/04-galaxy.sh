#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Krok 4: Ansible Galaxy role a kolekce                                       │
# │                                                                             │
# │ Co dělá:  Stáhne závislosti definované v requirements.yml.                  │
# │ Proč:     Playbook používá role třetích stran (geerlingguy.mac.*, apod.).   │
# │ Jak long: ~1 minuta.                                                        │
# │ Opakování: Bezpečné spustit vícekrát (přepíše stávající).                   │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

# Zajisti že brew je v PATH (Apple Silicon)
if ! command -v brew &>/dev/null && [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK_DIR="$(dirname "$SCRIPT_DIR")"

step "Ansible Galaxy role & kolekce"

if [[ ! -f "$PLAYBOOK_DIR/requirements.yml" ]]; then
  echo "Soubor requirements.yml nenalezen v $PLAYBOOK_DIR" >&2
  exit 1
fi

ansible-galaxy install -r "$PLAYBOOK_DIR/requirements.yml"

ok "Galaxy závislosti nainstalovány"
