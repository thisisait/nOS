#!/bin/bash
# brew-svc.sh — fast brew services replacement using launchctl
# Usage: brew-svc.sh start|stop|restart <service>
#
# brew services (brew 4.x) uses Ruby API that hangs 30min+ on macOS.
# This script uses direct launchctl unload/load — instant effect.
set -euo pipefail

ACTION="${1:?Usage: brew-svc.sh start|stop|restart <service>}"
SVC="${2:?Usage: brew-svc.sh start|stop|restart <service>}"

# Custom LaunchAgents (prefered over brew-managed plists — they have env vars)
# Add entries here when services need persistent EnvironmentVariables.
declare -A CUSTOM_AGENT_PLISTS=(
  [ollama]="$HOME/Library/LaunchAgents/com.ollama.agent.plist"
)

# plist locations (user vs system)
USER_PLIST="$HOME/Library/LaunchAgents/homebrew.mxcl.${SVC}.plist"
SYS_PLIST="/Library/LaunchDaemons/homebrew.mxcl.${SVC}.plist"
CUSTOM_PLIST="${CUSTOM_AGENT_PLISTS[$SVC]:-}"

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
