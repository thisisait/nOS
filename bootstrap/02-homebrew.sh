#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Step 2: Homebrew                                                            │
# │                                                                             │
# │ What it does: Installs the Homebrew package manager (/opt/homebrew).        │
# │ Why:          Ansible and all tools are installed via brew.                 │
# │ Duration:     ~2-5 minutes.                                                 │
# │ Note:         On Apple Silicon it installs to /opt/homebrew (not /usr/local).│
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

step "Homebrew"

if command -v brew &>/dev/null; then
  ok "Homebrew is installed ($(brew --version | head -1))"
  exit 0
fi

echo "Installing Homebrew..."
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add Homebrew to PATH for the rest of this script (Apple Silicon)
if [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

ok "Homebrew installed"
echo ""
echo "  If the brew command is not found, add to ~/.zprofile:"
echo "  eval \"\$(/opt/homebrew/bin/brew shellenv)\""
