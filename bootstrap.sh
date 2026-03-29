#!/bin/bash
# bootstrap.sh – spustí všechny kroky přípravy v pořadí
# ─────────────────────────────────────────────────────────────────────────────
# Ekvivalent "Run All Cells" v Jupyter notebooku.
# Jednotlivé kroky lze spouštět samostatně:
#
#   bash bootstrap/01-xcode-clt.sh   # Krok 1: Xcode CLT
#   bash bootstrap/02-homebrew.sh    # Krok 2: Homebrew
#   bash bootstrap/03-ansible.sh     # Krok 3: Ansible
#   bash bootstrap/04-galaxy.sh      # Krok 4: Galaxy role
#   bash bootstrap/05-config.sh      # Krok 5: config.yml + credentials.yml
#
# Po úspěšném bootstrap:
#   ansible-playbook main.yml -K
# ─────────────────────────────────────────────────────────────────────────────
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bootstrap"

bash "$DIR/01-xcode-clt.sh"
bash "$DIR/02-homebrew.sh"
bash "$DIR/03-ansible.sh"
bash "$DIR/04-galaxy.sh"
bash "$DIR/05-config.sh"

echo ""
echo -e "\033[1;32m╔══════════════════════════════════════════════════════╗\033[0m"
echo -e "\033[1;32m║  Bootstrap dokončen!                                 ║\033[0m"
echo -e "\033[1;32m╚══════════════════════════════════════════════════════╝\033[0m"
echo ""
echo "  Spusť playbook:"
echo "  ansible-playbook main.yml -K"
echo ""
