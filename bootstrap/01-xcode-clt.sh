#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Krok 1: Xcode Command Line Tools                                            │
# │                                                                             │
# │ Co dělá:  Nainstaluje Apple kompilátor (clang), git, make a dev tools.     │
# │ Proč:     Homebrew i Ansible potřebují CLT pro build nativních balíčků.     │
# │ Jak long: ~5-10 minut (stažení ~700 MB).                                   │
# │ Co udělat: Potvrdit dialog macOS → kliknout "Install".                      │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

step "Xcode Command Line Tools"

if xcode-select -p &>/dev/null; then
  ok "Xcode CLT je nainstalováno ($(xcode-select -p))"
  exit 0
fi

echo "Spouštím installer — potvrď v dialogovém okně macOS..."
xcode-select --install

echo "Čekám na dokončení instalace Xcode CLT (může trvat 5-10 min)..."
until xcode-select -p &>/dev/null; do sleep 5; done

ok "Xcode CLT nainstalováno"
