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
# Every setting has a default (default.config.yml); config.yml holds only your choices.
step "config.yml (feature toggles)"
if [[ -f "$PLAYBOOK_DIR/config.yml" ]]; then
  ok "config.yml already exists – skipping"
else
  cat > "$PLAYBOOK_DIR/config.yml" <<'YAML'
---
# Your choices only; every default lives in default.config.yml. A profile sets a whole
# service set at once: ansible-playbook main.yml -e @profiles/core.yml (see profiles/).
# The first run's preflight lists the settings still at their default.
# tenant_domain: dev.local
# host_alias: ""        # a second nOS host on the LAN: e.g. box -> kiwix.box.dev.local
YAML
  ok "Created a minimal config.yml"
fi

# ── credentials.yml ───────────────────────────────────────────────────────────
# Secrets derive from global_password_prefix: mint a strong one here, never printed.
step "credentials.yml (the password prefix)"
if grep -qE '^global_password_prefix: *"?[^"[:space:]]{12,}' "$PLAYBOOK_DIR/credentials.yml" 2>/dev/null; then
  ok "credentials.yml has a prefix – skipping"
else
  ( cd "$PLAYBOOK_DIR"; umask 077
    { grep -v '^global_password_prefix:' credentials.yml 2>/dev/null || true
      printf 'global_password_prefix: "%s"\n' "$(openssl rand -hex 16)"; } > credentials.yml.new
    mv credentials.yml.new credentials.yml )
  ok "Minted a random global_password_prefix into credentials.yml (0600, not shown)"
fi

# ── YAML validation ───────────────────────────────────────────────────────────
step "YAML validation"
VALID=true
# The first Python that has PyYAML: the Linux venv, Ansible's own interpreter (Homebrew's ansible
# on macOS), then python3. A fresh Mac's python3 has none (the spore rehearsal 11-04 read it as
# "YAML error"): with no PyYAML anywhere the files are not validated, which is not an error.
PY=""
for c in "$HOME/.local/share/nos/ansible-venv/bin/python" \
         "$(head -1 "$(command -v ansible-playbook 2>/dev/null || echo /dev/null)" 2>/dev/null | sed -n 's/^#! *//p' | cut -d' ' -f1)" python3; do
  [[ -n "$c" ]] && "$c" -c "import yaml" 2>/dev/null && { PY="$c"; break; }
done
[[ -n "$PY" ]] || warn "No Python with PyYAML yet: config.yml / credentials.yml not validated (the first nos run parses them)"

for f in config.yml credentials.yml; do
  if [[ -n "$PY" && -f "$PLAYBOOK_DIR/$f" ]]; then
    if "$PY" -c "import yaml,sys; yaml.safe_load(open('$PLAYBOOK_DIR/$f'))" 2>/dev/null; then
      ok "$f – YAML OK"
    else
      echo -e "\033[0;31m✗ $f – YAML error! Check the file.\033[0m" >&2
      "$PY" -c "import yaml,sys; yaml.safe_load(open('$PLAYBOOK_DIR/$f'))" 2>&1 | head -5
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
echo "  ansible-playbook main.yml     # asks for sudo once; installs the \`nos\` CLI"
