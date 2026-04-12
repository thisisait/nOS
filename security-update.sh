#!/bin/bash
# security-update.sh – aktualizace Docker stacku bez plneho playbook runu
# ─────────────────────────────────────────────────────────────────────────────
# Re-deploys compose soubory s aktualnimi verzemi z default.config.yml,
# stahne nove Docker images a restartuje kontejnery.
#
# Pouziti:
#   ./security-update.sh                    # update vsech stacku
#   ./security-update.sh --check            # dry run (zadne zmeny)
#   ./security-update.sh --tags nginx       # jen nginx reload
#
# Typicky workflow po CVE patchi:
#   1. Aktualizovat *_version v default.config.yml
#   2. Spustit ./security-update.sh
#   3. Overit: docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'

set -euo pipefail
cd "$(dirname "$0")"

echo "devBoxNOS security update"
echo "========================="
echo "version_policy: $(grep '^version_policy:' default.config.yml | awk '{print $2}' | tr -d '\"')"
echo ""

ansible-playbook main.yml -K --tags stacks "$@"
