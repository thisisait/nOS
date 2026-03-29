#!/bin/bash
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ Krok 5: Příprava konfiguračních souborů                                     │
# │                                                                             │
# │ Co dělá:  Vytvoří config.yml a credentials.yml ze šablon.                   │
# │ Proč:     Oba soubory jsou v .gitignore – osobní nastavení mimo repozitář.  │
# │                                                                             │
# │ Soubory:                                                                    │
# │   config.yml       – feature toggles (co zapnout/vypnout)                  │
# │   credentials.yml  – hesla a tokeny (NIKDY necommituj!)                     │
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
  ok "config.yml již existuje – přeskakuji"
else
  cp "$PLAYBOOK_DIR/config.example.yml" "$PLAYBOOK_DIR/config.yml"
  ok "Vytvořen config.yml ze šablony"
  echo "  Uprav: nano $PLAYBOOK_DIR/config.yml"
fi

# ── credentials.yml ───────────────────────────────────────────────────────────
step "credentials.yml (hesla a tokeny)"
if [[ -f "$PLAYBOOK_DIR/credentials.yml" ]]; then
  ok "credentials.yml již existuje – přeskakuji"
else
  cp "$PLAYBOOK_DIR/credentials.example.yml" "$PLAYBOOK_DIR/credentials.yml"
  ok "Vytvořen credentials.yml ze šablony"
  warn "DŮLEŽITÉ: Přepiš všechna 'changeme_*' hesla!"
  echo "  Uprav: nano $PLAYBOOK_DIR/credentials.yml"
fi

# ── Validace YAML ─────────────────────────────────────────────────────────────
step "Validace YAML"
VALID=true

for f in config.yml credentials.yml; do
  if [[ -f "$PLAYBOOK_DIR/$f" ]]; then
    if python3 -c "import yaml,sys; yaml.safe_load(open('$PLAYBOOK_DIR/$f'))" 2>/dev/null; then
      ok "$f – YAML OK"
    else
      echo -e "\033[0;31m✗ $f – YAML chyba! Zkontroluj soubor.\033[0m" >&2
      python3 -c "import yaml,sys; yaml.safe_load(open('$PLAYBOOK_DIR/$f'))" 2>&1 | head -5
      VALID=false
    fi
  fi
done

if [[ "$VALID" != "true" ]]; then
  echo ""
  warn "Oprav YAML chyby před spuštěním playbooku."
  exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}Konfigurace připravena. Další krok:${NC}"
echo "  ansible-playbook main.yml -K"
