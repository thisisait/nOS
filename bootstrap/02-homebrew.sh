#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Krok 2: Homebrew                                                            │
# │                                                                             │
# │ Co dělá:  Nainstaluje balíčkový manažer Homebrew (/opt/homebrew).          │
# │ Proč:     Ansible a všechny nástroje se instalují přes brew.                │
# │ Jak long: ~2-5 minut.                                                       │
# │ Pozn.:    Na Apple Silicon se instaluje do /opt/homebrew (ne /usr/local).   │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

step "Homebrew"

if command -v brew &>/dev/null; then
  ok "Homebrew je nainstalováno ($(brew --version | head -1))"
  exit 0
fi

echo "Instaluji Homebrew..."
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Přidej Homebrew do PATH pro zbytek tohoto skriptu (Apple Silicon)
if [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

ok "Homebrew nainstalováno"
echo ""
echo "  Pokud brew příkaz nenajdeš, přidej do ~/.zprofile:"
echo "  eval \"\$(/opt/homebrew/bin/brew shellenv)\""
