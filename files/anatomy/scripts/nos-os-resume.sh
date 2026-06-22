#!/usr/bin/env bash
# =============================================================================
# nos-os-resume.sh — the cross-reboot continuation executor.
#
# Invoked by the launchd login agent (eu.thisisait.nos.resume, RunAtLoad) on
# EVERY login. It is a no-op unless a continuation plan is armed AND the host has
# actually rebooted into a DIFFERENT macOS since the plan was armed — i.e. the
# operator-triggered macOS update happened. Then it runs the settle and clears
# the plan. This is what makes "nOS settles itself after the update + restart"
# true, with the operator's only manual act being the OS update trigger itself.
#
# Decision table (boot-id armed at PRE-time vs the live boot-id):
#   - no plan ........................... exit 0 (nothing armed)
#   - boot-id UNCHANGED ................. exit 0 (not rebooted yet — still PRE)
#   - boot-id CHANGED, OS version SAME .. re-arm against this boot, keep waiting
#                                         (an unrelated reboot, not the update)
#   - boot-id CHANGED, OS version DIFF .. THE UPDATE — run settle, archive plan,
#                                         notify the operator (macOS notification)
#
# Sudo-free. One-shot per real update (plan archived) so logins don't re-loop.
# =============================================================================
set -uo pipefail

NOS_DIR="${NOS_DIR:-${HOME}/.nos}"
PLAN="${NOS_DIR}/continuation-plan.json"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ -f "$PLAN" ] || exit 0
command -v jq >/dev/null 2>&1 || { echo "nos-os-resume: jq not found — cannot read plan" >&2; exit 0; }

boot_now="$("$HERE/nos-boot-id.sh")"
armed_boot="$(jq -r '.armed_boot_id // empty' "$PLAN" 2>/dev/null || true)"
os_before="$(jq -r '.os_version_before // empty' "$PLAN" 2>/dev/null || true)"

# Not rebooted since arm → still in the PRE window (or a plain re-login).
[ -n "$armed_boot" ] && [ "$boot_now" = "$armed_boot" ] && exit 0

os_now="$(sw_vers -productVersion 2>/dev/null || uname -r)"
ts="$(date +%Y%m%dT%H%M%S)"
log="${NOS_DIR}/os-resume-${ts}.log"

if [ -n "$os_before" ] && [ "$os_now" = "$os_before" ]; then
  # Rebooted, but the OS version did NOT change → this was some OTHER reboot,
  # not the planned macOS update. Re-arm against the new boot id and keep waiting
  # (so settle does not fire prematurely + the plan is not lost before the update).
  tmp="$(mktemp)"
  if jq --arg b "$boot_now" '.armed_boot_id=$b' "$PLAN" > "$tmp" 2>/dev/null; then
    mv "$tmp" "$PLAN"
  else
    rm -f "$tmp"
  fi
  echo "[nos-os-resume] rebooted but OS unchanged ($os_now); plan kept armed, waiting for the update." | tee -a "$log"
  exit 0
fi

# The planned macOS update happened (OS version changed across the reboot).
{
  echo "[nos-os-resume] $(date '+%Y-%m-%d %H:%M:%S') — OS ${os_before:-?} -> ${os_now}; running settle..."
} | tee -a "$log"

# Dry-run hook (test / operator preview): prove the decision was reached without
# running settle, archiving the plan, or posting a notification.
if [ "${NOS_RESUME_DRY:-0}" = "1" ]; then
  echo "[nos-os-resume][dry] would run settle for OS ${os_before:-?} -> ${os_now}; plan left in place." | tee -a "$log"
  exit 0
fi

"$HERE/nos-os-settle.sh" >> "$log" 2>&1
rc=$?

# One-shot: archive the plan so logins don't re-run settle in a loop.
mv "$PLAN" "${PLAN%.json}-done-${ts}.json" 2>/dev/null || rm -f "$PLAN"

# Record a machine-readable result Wing can surface later (increment 3). Count
# WARN / ATTENTION lines so the result + notification are honest: a WARN must not
# read as fully "clean" (rc only tracks ATTENTION = sudo/GUI-needed items).
warns="$(grep -c '^WARN:' "$log" 2>/dev/null)"; warns="${warns:-0}"
attn="$(grep -c 'ATTENTION:' "$log" 2>/dev/null)"; attn="${attn:-0}"
res="${NOS_DIR}/os-resume-result.json"
jq -n --arg ob "${os_before:-}" --arg on "$os_now" --arg t "$ts" --argjson rc "$rc" \
  --argjson warns "$warns" --argjson attn "$attn" --arg log "$log" \
  '{kind:"os-resume", os_before:$ob, os_after:$on, settled_at:$t, settle_rc:$rc,
    warnings:$warns, attention:$attn, log:$log, clean:($rc==0 and $warns==0)}' \
  > "$res" 2>/dev/null || true

# Tell the operator (they are at the machine — a native notification is enough
# for v0; the A9/Bone fanout comes in increment 3).
if [ "$rc" -ne 0 ]; then
  msg="nOS settle after the macOS update needs attention (${attn} item(s)) — see ${log}."
elif [ "$warns" -gt 0 ]; then
  msg="nOS settled after the macOS update (${os_before:-?} → ${os_now}) with ${warns} warning(s) — see ${log}."
else
  msg="nOS settled after the macOS update (${os_before:-?} → ${os_now}). All clear."
fi
osascript -e "display notification \"${msg}\" with title \"nOS\"" >/dev/null 2>&1 || true
echo "[nos-os-resume] settle rc=${rc}; plan archived; ${msg}" | tee -a "$log"
exit 0
