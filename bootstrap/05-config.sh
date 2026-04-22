#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Step 5: Prepare configuration files                                         │
# │                                                                             │
# │ What it does: Creates config.yml and credentials.yml from templates.        │
# │ Why:          Both files are in .gitignore – personal settings outside repo.│
# │                                                                             │
# │ Files:                                                                      │
# │   config.yml       – feature toggles (what to enable/disable)               │
# │   credentials.yml  – passwords and tokens (NEVER commit!)                   │
# └─────────────────────────────────────────────────────────────────────────────┘
set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
step() { echo -e "\n${BOLD}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK_DIR="$(dirname "$SCRIPT_DIR")"

# ── config.yml ────────────────────────────────────────────────────────────────
step "config.yml (feature toggles)"
if [[ -f "$PLAYBOOK_DIR/config.yml" ]]; then
  ok "config.yml already exists – skipping"
else
  cp "$PLAYBOOK_DIR/config.example.yml" "$PLAYBOOK_DIR/config.yml"
  ok "Created config.yml from template"
  echo "  Edit: nano $PLAYBOOK_DIR/config.yml"
fi

# ── credentials.yml ───────────────────────────────────────────────────────────
step "credentials.yml (passwords and tokens)"
if [[ -f "$PLAYBOOK_DIR/credentials.yml" ]]; then
  ok "credentials.yml already exists – skipping"
else
  cp "$PLAYBOOK_DIR/credentials.example.yml" "$PLAYBOOK_DIR/credentials.yml"
  ok "Created credentials.yml from template"
  warn "IMPORTANT: Replace all 'changeme_*' passwords!"
  echo "  Edit: nano $PLAYBOOK_DIR/credentials.yml"
fi

# ── YAML validation ───────────────────────────────────────────────────────────
step "YAML validation"
VALID=true

for f in config.yml credentials.yml; do
  if [[ -f "$PLAYBOOK_DIR/$f" ]]; then
    if python3 -c "import yaml,sys; yaml.safe_load(open('$PLAYBOOK_DIR/$f'))" 2>/dev/null; then
      ok "$f – YAML OK"
    else
      echo -e "\033[0;31m✗ $f – YAML error! Check the file.\033[0m" >&2
      python3 -c "import yaml,sys; yaml.safe_load(open('$PLAYBOOK_DIR/$f'))" 2>&1 | head -5
      VALID=false
    fi
  fi
done

if [[ "$VALID" != "true" ]]; then
  echo ""
  warn "Fix YAML errors before running the playbook."
  exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}Configuration ready. Next step:${NC}"
echo "  ansible-playbook main.yml -K"
