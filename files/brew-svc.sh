#!/bin/bash
# brew-svc.sh — fast brew services replacement using launchctl
# Usage: brew-svc.sh start|stop|restart <service>
#
# brew services (brew 4.x) uses Ruby API that hangs 30min+ on macOS.
# This script uses direct launchctl unload/load — instant effect.
#
# Compatible with macOS system bash 3.2 (no associative arrays, no declare -A).
set -euo pipefail

ACTION="${1:?Usage: brew-svc.sh start|stop|restart <service>}"
SVC="${2:?Usage: brew-svc.sh start|stop|restart <service>}"

# Custom LaunchAgents (prefered over brew-managed plists — they have env vars).
# Add a case here when services need persistent EnvironmentVariables.
custom_plist_for() {
  case "$1" in
    ollama) echo "$HOME/Library/LaunchAgents/com.ollama.agent.plist" ;;
    *)      echo "" ;;
  esac
}

# plist locations (user vs system). Each formula names its own plist:
# Homebrew 7 formulae ship sh.brew.<svc> (alloy, ollama, redis), older ones
# homebrew.mxcl.<svc> (dnsmasq). The old-only lookup missed sh.brew.* and a
# leave left alloy listening on three ports (2026-09-30).
USER_PLIST=""; SYS_PLIST=""
for pfx in sh.brew homebrew.mxcl; do
  [ -z "$USER_PLIST" ] && [ -f "$HOME/Library/LaunchAgents/${pfx}.${SVC}.plist" ] && USER_PLIST="$HOME/Library/LaunchAgents/${pfx}.${SVC}.plist"
  [ -z "$SYS_PLIST" ] && [ -f "/Library/LaunchDaemons/${pfx}.${SVC}.plist" ] && SYS_PLIST="/Library/LaunchDaemons/${pfx}.${SVC}.plist"
done
CUSTOM_PLIST="$(custom_plist_for "$SVC")"

do_stop() {
  # Custom LaunchAgent (if defined for this service) takes priority
  [ -n "$CUSTOM_PLIST" ] && [ -f "$CUSTOM_PLIST" ] && launchctl unload "$CUSTOM_PLIST" 2>/dev/null || true
  [ -f "$USER_PLIST" ] && launchctl unload "$USER_PLIST" 2>/dev/null || true
  [ -f "$SYS_PLIST" ] && sudo launchctl unload "$SYS_PLIST" 2>/dev/null || true
}

do_start() {
  # Priorita: custom LaunchAgent (env vars) → brew user → brew system → brew CLI
  if [ -n "$CUSTOM_PLIST" ] && [ -f "$CUSTOM_PLIST" ]; then
    launchctl load "$CUSTOM_PLIST" 2>/dev/null || true
  elif [ -f "$USER_PLIST" ]; then
    launchctl load "$USER_PLIST" 2>/dev/null || true
  elif [ -f "$SYS_PLIST" ]; then
    sudo launchctl load "$SYS_PLIST" 2>/dev/null || true
  else
    # Fallback: let brew generate the plist first time
    brew services start "$SVC" 2>/dev/null &
    BREW_PID=$!
    ( sleep 30 && kill $BREW_PID 2>/dev/null ) &
    wait $BREW_PID 2>/dev/null || true
  fi
}

case "$ACTION" in
  stop)    do_stop ;;
  start)   do_start ;;
  restart) do_stop; sleep 1; do_start ;;
  *)       echo "Unknown action: $ACTION" >&2; exit 1 ;;
esac
