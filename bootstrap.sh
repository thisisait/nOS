#!/bin/bash
# bootstrap.sh – runs all preparation steps in order
# ─────────────────────────────────────────────────────────────────────────────
# Equivalent of "Run All Cells" in a Jupyter notebook.
# Individual steps can be run separately:
#
#   bash bootstrap/01-xcode-clt.sh   # Step 1: Xcode CLT
#   bash bootstrap/02-homebrew.sh    # Step 2: Homebrew
#   bash bootstrap/03-ansible.sh     # Step 3: Ansible
#   bash bootstrap/04-galaxy.sh      # Step 4: Galaxy roles
#   bash bootstrap/05-config.sh      # Step 5: config.yml + credentials.yml
#
# After successful bootstrap:
#   ansible-playbook main.yml -K
# ─────────────────────────────────────────────────────────────────────────────
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bootstrap"

bash "$DIR/01-xcode-clt.sh"
bash "$DIR/02-homebrew.sh"
bash "$DIR/03-ansible.sh"
bash "$DIR/04-galaxy.sh"
bash "$DIR/05-config.sh"

# ansible.cfg logs to ~/.nos/ansible.log and Ansible never creates the
# directory, so a first run straight after bootstrap would log nothing.
mkdir -p "$HOME/.nos" && chmod 700 "$HOME/.nos"

echo ""
echo -e "\033[1;32m╔══════════════════════════════════════════════════════╗\033[0m"
echo -e "\033[1;32m║  Bootstrap complete!                                 ║\033[0m"
echo -e "\033[1;32m╚══════════════════════════════════════════════════════╝\033[0m"
echo ""
echo "  Run the playbook:"
echo "  ansible-playbook main.yml     # asks for sudo once; installs the \`nos\` CLI"
echo ""
