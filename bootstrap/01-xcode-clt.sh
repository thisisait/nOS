#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Step 1: Xcode Command Line Tools                                            │
# │                                                                             │
# │ What it does: Installs Apple compiler (clang), git, make and dev tools.     │
# │ Why:          Homebrew and Ansible need CLT to build native packages.       │
# │ Duration:     ~5-10 minutes (~700 MB download).                             │
# │ Action:       Confirm macOS dialog -> click "Install".                      │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

step "Xcode Command Line Tools"

if xcode-select -p &>/dev/null; then
  ok "Xcode CLT is installed ($(xcode-select -p))"
  exit 0
fi

echo "Launching installer — confirm in the macOS dialog..."
xcode-select --install

echo "Waiting for Xcode CLT installation to finish (may take 5-10 min)..."
until xcode-select -p &>/dev/null; do sleep 5; done

ok "Xcode CLT installed"
