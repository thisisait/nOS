#!/usr/bin/env bash
# =============================================================================
# nos-upgrade-detached.sh — run an upgrade DETACHED from the controlling TTY.
#
# The whole point: a SESSION-RISK upgrade (reset.scope host_app / host_reboot)
# may restart a host app or reboot the machine and DROP the operator's
# terminal/IDE session mid-run. If the run is tied to that session, the death
# of the session ABORTS the upgrade, leaving it half-applied. This launcher
# detaches the `ansible-playbook --tags upgrade` run from the controlling TTY so
# the operator's IDE/terminal dying does NOT kill the upgrade.
#
# It runs:
#   ansible-playbook main.yml --tags upgrade \
#     -e upgrade_service=<service> [-e upgrade_recipe_id=<recipe_id>] \
#     -e upgrade_confirmed=true -e auto_upgrade=true
#
# Both confirm flags are passed deliberately so the headless run NEVER blocks on
# an interactive prompt: the engine has TWO pre-apply pauses with DIFFERENT escape
# hatches — the breaking/security confirm keys off `auto_upgrade=true`, and the
# session-risk (host_app/host_reboot) confirm keys off `upgrade_confirmed=true`.
# The operator already chose "detached" (in the Wing plan-choice modal, or simply
# by invoking this script), so re-prompting on a TTY-less run would only hang it.
#
# Detachment:
#   - macOS: `caffeinate -ims` (keep the system awake + alive for the run's
#     duration) wrapping `nohup … &` — survives the controlling TTY closing.
#   - Linux: `setsid nohup … &` — a new session leader fully detached from the
#     login session, so a logout / SSH teardown does NOT reap it (a systemd
#     `--user --scope` would be subject to logind KillUserProcesses). No caffeinate.
#
# Output goes to ~/.nos/upgrade-<service>-<timestamp>.log; the PID is recorded
# in ~/.nos/upgrade-<service>.pid. The script prints the log path + PID + a
# `tail -f` hint and RETURNS IMMEDIATELY — it does not wait for the upgrade.
#
# By design this launcher is host-disruptive-verb-FREE: it only LAUNCHES the
# playbook. It contains no killall / reboot / shutdown — the engine + recipe own
# any disruptive step, gated behind the operator's confirmed choice.
#
# Usage:
#   tools/nos-upgrade-detached.sh <service> [recipe_id]
#
# Examples:
#   tools/nos-upgrade-detached.sh postgresql
#   tools/nos-upgrade-detached.sh grafana grafana-11-to-12
#
# Refuses `blank=true` (a wipe/reinstall needs sudo + a human, never detached).
# Requires no sudo.
#
# Exit codes (of THIS launcher — not the upgrade it spawns):
#   0 — upgrade launched detached; log path + PID printed.
#   2 — bad usage / refused argument / ansible-playbook not found.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
Usage:
  tools/nos-upgrade-detached.sh <service> [recipe_id]

Examples:
  tools/nos-upgrade-detached.sh postgresql
  tools/nos-upgrade-detached.sh grafana grafana-11-to-12

Runs `ansible-playbook --tags upgrade` DETACHED from the controlling TTY so the
upgrade survives the operator's terminal/IDE dying. Refuses blank=true.
EOF
}

SERVICE="${1:-}"
RECIPE_ID="${2:-}"

if [[ -z "$SERVICE" || "$SERVICE" == "-h" || "$SERVICE" == "--help" ]]; then
  usage
  exit 2
fi

# Refuse destructive / sudo-requiring invocations: a service or recipe argument
# must never smuggle in a blank/destroy request.
for arg in "$SERVICE" "$RECIPE_ID"; do
  case "$arg" in
    *blank=true*|*destroy_state=true*|*remove=data*|*remove=deep*|*remove=all*|*flush=true*|*flush=deep*|*uninstall=true*|confirm=true*|*[!_a-zA-Z0-9]confirm=true*)
      echo "nos-upgrade-detached.sh: refusing — '$arg' is a removal/destructive token; needs a human." >&2
      echo "  Use: nos --remove=<level> --confirm  (or ansible-playbook main.yml -e remove=<level> -e confirm=true)" >&2
      exit 2
      ;;
  esac
done

command -v ansible-playbook >/dev/null \
  || { echo "nos-upgrade-detached.sh: ansible-playbook not found on PATH" >&2; exit 2; }

NOS_DIR="${HOME}/.nos"
mkdir -p "$NOS_DIR"
chmod 700 "$NOS_DIR"   # match the engine's 0700 contract for the runtime sidecar
TS="$(date +%Y%m%dT%H%M%S)"
LOG="${NOS_DIR}/upgrade-${SERVICE}-${TS}.log"
PIDFILE="${NOS_DIR}/upgrade-${SERVICE}.pid"

# Build the ansible-playbook argv. upgrade_confirmed=true (session-risk pause) +
# auto_upgrade=true (breaking/security pause) so neither engine pause blocks this
# headless run.
PLAY_ARGS=(
  main.yml
  --tags upgrade
  -e "upgrade_service=${SERVICE}"
  -e upgrade_confirmed=true
  -e auto_upgrade=true
)
if [[ -n "$RECIPE_ID" ]]; then
  PLAY_ARGS+=(-e "upgrade_recipe_id=${RECIPE_ID}")
fi

echo "[nos-upgrade-detached] launching upgrade for '${SERVICE}'${RECIPE_ID:+ (recipe ${RECIPE_ID})} — DETACHED"
echo "[nos-upgrade-detached] log:     ${LOG}"

case "$(uname -s)" in
  Darwin)
    # caffeinate -ims keeps the host awake + the assertion alive for the child's
    # lifetime; nohup detaches from the controlling TTY so closing the terminal
    # / IDE does not SIGHUP the run.
    nohup caffeinate -ims ansible-playbook "${PLAY_ARGS[@]}" </dev/null >"$LOG" 2>&1 &
    PID=$!
    ;;
  Linux)
    # setsid makes the run a new session leader fully detached from the login
    # session and nohup ignores SIGHUP — so a terminal close OR a full logout /
    # SSH teardown cannot reap it. (A systemd `--user --scope` would be subject
    # to logind's KillUserProcesses=yes on logout, so it is deliberately NOT used
    # despite "outliving the terminal" — it does not outlive the SESSION.) $! is
    # the real ansible-playbook PID here, so the pidfile is accurate.
    setsid nohup ansible-playbook "${PLAY_ARGS[@]}" </dev/null >"$LOG" 2>&1 &
    PID=$!
    ;;
  *)
    # Unknown platform: best-effort detach with setsid/nohup, no caffeinate.
    setsid nohup ansible-playbook "${PLAY_ARGS[@]}" </dev/null >"$LOG" 2>&1 &
    PID=$!
    ;;
esac

echo "$PID" >"$PIDFILE"
echo "[nos-upgrade-detached] pid:     ${PID}  (recorded in ${PIDFILE})"
echo "[nos-upgrade-detached] follow:  tail -f ${LOG}"
echo "[nos-upgrade-detached] the run survives this terminal closing."
exit 0
