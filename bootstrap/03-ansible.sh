#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Step 3: Ansible                                                             │
# │                                                                             │
# │ What it does: macOS: Ansible via Homebrew. Linux: a venv with the pinned    │
# │               ansible-core and what nOS's modules import                    │
# │               (requirements-controller.txt), linked into ~/.local/bin.      │
# │ Why:          Ansible is the engine that runs the playbook.                 │
# │ Duration:     ~1-2 minutes.                                                 │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ="$SCRIPT_DIR/requirements-controller.txt"

step "Ansible"

if [[ "$(uname -s)" != Darwin ]]; then
  VENV="${NOS_ANSIBLE_VENV:-$HOME/.local/share/nos/ansible-venv}"
  python3 -m venv --help >/dev/null 2>&1 && python3 -c 'import ensurepip' 2>/dev/null || {
    echo "python3 cannot make a venv here. Once: sudo apt install -y python3-venv" >&2; exit 1; }
  [[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r "$REQ"
  mkdir -p "$HOME/.local/bin"
  for b in ansible ansible-playbook ansible-galaxy ansible-config ansible-inventory; do
    ln -sf "$VENV/bin/$b" "$HOME/.local/bin/$b"
  done
  ok "Ansible in $VENV ($("$VENV/bin/ansible" --version | head -1)), linked into ~/.local/bin"
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  ~/.local/bin is not on PATH yet: open a new login shell (or: export PATH=\"\$HOME/.local/bin:\$PATH\")" ;; esac
  exit 0
fi

# Make sure brew is in PATH (Apple Silicon)
if ! command -v brew &>/dev/null && [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# ponytail: macOS keeps the brew/pyenv controller as it is; requirements-controller.txt is Linux's until a Mac blank proves it
if command -v ansible &>/dev/null; then
  ok "Ansible is installed ($(ansible --version | head -1))"
  exit 0
fi

echo "Installing Ansible via Homebrew..."
brew install ansible

ok "Ansible installed"
