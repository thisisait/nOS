#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Step 3: Ansible                                                             │
# │                                                                             │
# │ What it does: Installs Ansible via Homebrew.                                │
# │ Why:          Ansible is the engine that runs the playbook.                 │
# │ Duration:     ~1-2 minutes.                                                 │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

# Make sure brew is in PATH (Apple Silicon)
if ! command -v brew &>/dev/null && [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

step "Ansible"

if command -v ansible &>/dev/null; then
  ok "Ansible is installed ($(ansible --version | head -1))"
  exit 0
fi

echo "Installing Ansible via Homebrew..."
brew install ansible

ok "Ansible installed"
