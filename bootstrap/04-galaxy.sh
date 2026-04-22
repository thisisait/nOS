#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Step 4: Ansible Galaxy roles and collections                                │
# │                                                                             │
# │ What it does: Downloads dependencies defined in requirements.yml.           │
# │ Why:          Playbook uses third-party roles (geerlingguy.mac.*, etc.).    │
# │ Duration:     ~1 minute.                                                    │
# │ Repeatable:   Safe to run multiple times (overwrites existing).             │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

# Make sure brew is in PATH (Apple Silicon)
if ! command -v brew &>/dev/null && [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK_DIR="$(dirname "$SCRIPT_DIR")"

step "Ansible Galaxy roles & collections"

if [[ ! -f "$PLAYBOOK_DIR/requirements.yml" ]]; then
  echo "File requirements.yml not found in $PLAYBOOK_DIR" >&2
  exit 1
fi

ansible-galaxy install -r "$PLAYBOOK_DIR/requirements.yml"

ok "Galaxy dependencies installed"
