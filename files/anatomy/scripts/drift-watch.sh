#!/usr/bin/env bash
# =============================================================================
# drift-watch.sh — scheduled security-drift watcher (Nervy, 2026-05-25).
# -----------------------------------------------------------------------------
# Closes the OPEN "A8 conductor scheduled drift scans" gap WITHOUT an LLM: runs
# the deterministic drift-check probe (hooks/playbook-end.d/20-cve-drift-check.sh)
# on a Pulse schedule so the Prometheus drift metric refreshes daily (not only
# at playbook-end), and emits an HMAC-signed notification to Bone when the scan
# has gone stale (>14d) or CRITICAL remediations are pending.
#
# Promotes the "manual interim refresh path" (CLAUDE.md Known Tech Debt) to an
# autonomous self-monitoring loop. The actual scan REFRESH (updating
# last_full_scan) still needs the agentic scan-runner — this watcher makes the
# staleness LOUD so it can't rot silently between playbook runs.
#
# Env (Pulse job provides):
#   NOS_REPO                  repo root (default: derived from script path)
#   WING_EVENTS_HMAC_SECRET   Bone HMAC seed; unset → metric-only, no notify
#   BONE_API_URL              default http://127.0.0.1:8099 (Bone; 9000 is Wing)
#   DRIFT_STALE_HOURS         staleness threshold (default 336 = 14 days)
# Exit 0 always (a watcher must not fail the Pulse runner).
# =============================================================================

set -uo pipefail

NOS_REPO="${NOS_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}"
HOOK="${NOS_REPO}/hooks/playbook-end.d/20-cve-drift-check.sh"
BONE_URL="${BONE_API_URL:-http://127.0.0.1:8099}"
STALE_H="${DRIFT_STALE_HOURS:-336}"

if ! command -v jq >/dev/null 2>&1; then
    echo "drift-watch: jq missing — skip" >&2
    exit 0
fi
if [[ ! -x "$HOOK" && ! -f "$HOOK" ]]; then
    echo "drift-watch: drift-check hook not found at $HOOK — skip" >&2
    exit 0
fi

# Run the probe; it refreshes the Prometheus textfile + prints ONE (pretty-
# printed, multi-line) snapshot JSON object on stdout. Capture all of it.
SNAP="$(NOS_REPO="$NOS_REPO" bash "$HOOK" 2>/dev/null)"
if ! echo "$SNAP" | jq -e . >/dev/null 2>&1; then
    echo "drift-watch: drift-check produced no JSON — skip" >&2
    exit 0
fi

# counts may be nested under .counts or spread at top level — handle both.
crit=$(echo "$SNAP" | jq -r '(.pending_critical // .counts.pending_critical // 0)')
high=$(echo "$SNAP" | jq -r '(.pending_high // .counts.pending_high // 0)')
age_h=$(echo "$SNAP" | jq -r '(.last_full_scan_age_hours // -1)')

echo "drift-watch: scan_age_h=${age_h} pending_critical=${crit} pending_high=${high} (stale>${STALE_H}h)"

# Decide whether to alert + at what severity.
sev=""; title=""
if [[ "${crit:-0}" -gt 0 ]]; then
    sev="critical"
    title="${crit} CRITICAL security finding(s) pending remediation"
elif [[ "${age_h}" -lt 0 ]]; then
    sev="high"
    title="Security scan never completed — run a full scan"
elif [[ "${age_h}" -gt "${STALE_H}" ]]; then
    sev="high"
    title="Security scan stale: $(( age_h / 24 ))d old (>$(( STALE_H / 24 ))d) — refresh needed"
fi

if [[ -z "$sev" ]]; then
    echo "drift-watch: within thresholds — metric refreshed, no notification"
    exit 0
fi

if [[ -z "${WING_EVENTS_HMAC_SECRET:-}" ]]; then
    echo "drift-watch: ALERT (${sev}) but WING_EVENTS_HMAC_SECRET unset — metric-only"
    exit 0
fi

BODY=$(jq -n \
    --arg sev "$sev" --arg title "$title" \
    --arg crit "$crit" --arg high "$high" --arg age "$age_h" \
    '{severity: $sev, title: $title,
      body: ("Pending: " + $crit + " critical, " + $high + " high. Last full scan " + $age + "h ago. Source: docs/llm/security/remediation-queue.json."),
      origin_plugin: "security-drift", actor_id: "pulse:drift-watch",
      # The drift verdict is a SNAPSHOT of the queue, so a newer one makes
      # the older false by construction. Four unread rows each said "1
      # critical, 11 high pending"; all four were true when sent and none
      # was true by the afternoon (docs/hidden_fees/26). Superseding is not
      # marking them read — nobody read them.
      supersede_key: "security-drift-verdict",
      actor_action_id: ("drift-" + (now | floor | tostring)),
      metadata: {pending_critical: $crit, pending_high: $high, scan_age_hours: $age}}')

# Canonical (sort_keys + compact) so Bone's HMAC verifier matches (it re-dumps
# with separators=(',',':'), sort_keys=True). Mirrors run-gitleaks.sh.
# -a + printf: Bone re-serialises with Python json.dumps (ensure_ascii true),
# and `echo` would expand a \n inside a JSON string into a literal newline.
BODY_C=$(printf '%s' "$BODY" | jq -a --sort-keys -c .)
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY_C" \
      | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" | awk '{print $NF}')
CODE=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
    -H "X-Wing-Timestamp: $TS" -H "X-Wing-Signature: $SIG" \
    -H "Content-Type: application/json" \
    -d "$BODY_C" "$BONE_URL/api/v1/notifications" 2>&1 || echo "000")
if [[ "$CODE" == "200" || "$CODE" == "201" ]]; then
    echo "drift-watch: notification emitted (severity=${sev})"
else
    echo "drift-watch: notification POST HTTP ${CODE} — metric still refreshed" >&2
fi
exit 0
