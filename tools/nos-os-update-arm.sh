#!/usr/bin/env bash
# =============================================================================
# nos-os-update-arm.sh — arm the cross-reboot continuation BEFORE a macOS update.
#
# The PRE phase of "macOS as a managed upgrade target" (the operator triggers the
# OS update; nOS handles the continuity). This records the current boot id + OS
# version into ~/.nos/continuation-plan.json so that, after the operator runs the
# macOS update + restart, the login agent (eu.thisisait.nos.resume) detects the
# reboot-into-a-new-OS and runs the settle automatically — no manual checklist.
#
# Usage:  tools/nos-os-update-arm.sh
# Then:   run the macOS update + restart yourself. After you log back in, nOS
#         settles on its own and posts a notification. Watch ~/.nos/os-resume-*.log
#
# Sudo-free. Safe to run anytime — it only writes a plan file; the resume agent
# acts only once the host has actually rebooted into a different macOS version.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
NOS_DIR="${NOS_DIR:-${HOME}/.nos}"
PLAN="${NOS_DIR}/continuation-plan.json"

command -v jq >/dev/null 2>&1 || { echo "nos-os-update-arm: jq is required" >&2; exit 2; }
mkdir -p "$NOS_DIR"
chmod 700 "$NOS_DIR" 2>/dev/null || true

boot="$(files/anatomy/scripts/nos-boot-id.sh)"
osver="$(sw_vers -productVersion 2>/dev/null || uname -r)"
build="$(sw_vers -buildVersion 2>/dev/null || true)"
armed_at="$(date '+%Y-%m-%dT%H:%M:%S')"

if [ -f "$PLAN" ]; then
  echo "[nos-os-update-arm] note: a continuation plan was already armed — overwriting it." >&2
fi

jq -n \
  --arg b "$boot" --arg o "$osver" --arg bd "$build" --arg t "$armed_at" \
  '{kind:"os-update", reason:"macOS update", armed_at:$t,
    armed_boot_id:$b, os_version_before:$o, os_build_before:$bd,
    settle:"os-settle"}' \
  > "$PLAN"

echo "[nos-os-update-arm] armed."
echo "  current OS : ${osver} (${build})"
echo "  boot-id    : ${boot}"
echo "  plan       : ${PLAN}"
echo ""
echo "  → Safe to run the macOS update + restart now."
echo "    After you log back in, nOS settles automatically (Docker up + host"
echo "    health verify) and posts a notification. Watch: ${NOS_DIR}/os-resume-*.log"
echo "    To cancel: rm '${PLAN}'"
