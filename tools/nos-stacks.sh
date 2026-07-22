#!/usr/bin/env bash
# =============================================================================
# nos-stacks.sh — run the Docker stack layer autonomously (no sudo, no prompt).
#
# For unattended / agent-driven development: bring up or reconverge Docker
# stacks (or a single service) WITHOUT the interactive sudo prompt and WITHOUT
# ever invoking sudo.
#
# Why this is safe (sudo review, 2026-05-23):
#   - The compose-up flow (tasks/stacks/core-up.yml + stack-up.yml) and the
#     plugin loader use ZERO `become:` — they only talk to the Docker daemon
#     (rootless on macOS / Docker Desktop) and write to ~/stacks + ~/.nos.
#   - Every `become: true` task lives in HOST setup (dnsmasq, sudoers,
#     macos-defaults, power-management, system-services, tls-certs,
#     docker-prereqs). None carry the 'stacks'/'core' tag, and none are tagged
#     'always' — so `--tags stacks` (etc.) skips them entirely.
#   - The only sudo gate is main.yml's `vars_prompt: nos_sudo_password`, which
#     fires at play start regardless of tags. Passing it via -e skips the prompt
#     (extra-vars outrank vars_prompt); the empty value is never used because no
#     selected task escalates. stdin is also redirected from /dev/null so even
#     if a future task added a prompt, this never hangs a CI / agent run.
#
# Usage:
#   tools/nos-stacks.sh                 # all stacks (core + wave-2)
#   tools/nos-stacks.sh woodpecker      # one service (A17 render + recreate)
#   tools/nos-stacks.sh observability   # one stack
#   tools/nos-stacks.sh stacks -e install_gitea=true --check
#
# First arg = --tags value (default: core,stacks). Remaining args pass through
# to ansible-playbook. Refuses to run if `blank=true` is requested (that path
# DOES need sudo + a human) — use the normal `ansible-playbook` invocation for
# destructive runs.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

TAGS="${1:-core,stacks}"
shift || true

for arg in "$@"; do
  case "$arg" in
    *blank=true*|*destroy_state=true*|*remove=data*|*remove=deep*|*remove=all*|*flush=true*|*flush=deep*|*uninstall=true*|confirm=true*|*[!_a-zA-Z0-9]confirm=true*)
      echo "nos-stacks.sh: refusing — '$arg' is a removal/destructive token; needs a human. Use:" >&2
      echo "  nos --remove=<level> --confirm    (once the nos CLI lands; until then:" >&2
      echo "  ansible-playbook main.yml -e remove=<level> -e confirm=true)" >&2
      exit 2
      ;;
  esac
done

echo "[nos-stacks] --tags ${TAGS}  (sudo-free, non-interactive)"
exec ansible-playbook main.yml \
  --tags "${TAGS}" \
  -e nos_sudo_password='' \
  "$@" </dev/null
