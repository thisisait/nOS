#!/usr/bin/env bash
# =============================================================================
# run-tofu-drift.sh — read-only OpenTofu Authentik drift check (ADR-0001 P2)
#
# READ-ONLY / PLAN-ONLY: this script runs `tofu plan` and NOTHING else. It
# NEVER applies — the only apply path for the Authentik tenant stays in
# tasks/tofu-authentik.yml (destroy-guarded, -parallelism=1). The plan runs
# with -lock=false: a read-only plan needs no state lock, and a stale lock
# left behind by a crashed operator plan/apply must never wedge the scheduled
# drift check (nor may the drift check ever block / force-unlock the
# operator's interactive run).
#
# Called by Pulse subprocess runner as the daily tofu-drift-plan job.
# Expects env vars (set via pulse_jobs.env_json):
#   NOS_TOFU_DIR            — terraform/authentik dir (default: repo root via $0)
#   WING_EVENTS_HMAC_SECRET — HMAC secret for Bone /api/v1/notifications
#                             (optional; unset = plan + log only, no notify)
#   BONE_API_URL            — Bone base URL (default: http://127.0.0.1:9000)
#   TOFU_PLAN_TIMEOUT_S     — internal plan watchdog (default: 540; kept BELOW
#                             the job's max_runtime_s=600 so the error-notify
#                             path fires before Pulse SIGKILLs the run)
#   PULSE_RUN_ID            — set by Pulse daemon; audit lineage id
#
# Exit codes (mirrors run-gitleaks.sh):
#   0 — no drift, or skipped cleanly (tofu binary / nos.auto.tfvars.json
#       absent — i.e. the tofu cutover hasn't run on this install)
#   1 — drift detected + notified (operator attention needed)
#   2 — plan error or timeout (notified at high severity; check stderr)
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
TOFU_DIR="${NOS_TOFU_DIR:-$REPO_ROOT/terraform/authentik}"
# 8099 is Bone, which verifies this HMAC; 9000 is Wing and answers 401.
BONE_URL="${BONE_API_URL:-http://127.0.0.1:8099}"
TIMEOUT_S="${TOFU_PLAN_TIMEOUT_S:-540}"
RUN_ID="${PULSE_RUN_ID:-manual-$(date +%s)}"

# ── Skip gates (pre-cutover installs must stay quiet) ─────────────────────────
# Pulse's catalog registers this job unconditionally (gdpr-breach-base
# precedent), so inertness lives HERE: both artifacts below exist only once
# the operator has run the tofu cutover (tasks/tofu-authentik.yml renders the
# tfvars + inits the dir). Pulse scrubs PATH overrides from job env, and the
# daemon's launchd PATH may lack the Homebrew prefix — probe absolute
# candidates after `command -v`.

TOFU_BIN=""
if command -v tofu &>/dev/null; then
    TOFU_BIN="$(command -v tofu)"
else
    for candidate in /opt/homebrew/bin/tofu /usr/local/bin/tofu /usr/bin/tofu; do
        if [[ -x "$candidate" ]]; then
            TOFU_BIN="$candidate"
            break
        fi
    done
fi

if [[ -z "$TOFU_BIN" ]]; then
    echo "INFO: tofu binary not found — skipping drift check (tofu cutover not installed)"
    exit 0
fi

if [[ ! -f "$TOFU_DIR/nos.auto.tfvars.json" ]]; then
    echo "INFO: $TOFU_DIR/nos.auto.tfvars.json absent — skipping drift check (tofu cutover has not rendered tfvars)"
    exit 0
fi

if ! command -v jq &>/dev/null; then
    echo "ERROR: jq not found in PATH" >&2
    exit 2
fi

# ── Notification emit (A9 fanout — gitleaks precedent mechanics) ─────────────
# POST to Bone /api/v1/notifications with HMAC-SHA256 signature. Channels are
# resolved by Bone's routing fallback against this plugin's severity block
# (drift → medium → wing-inbox; plan error → high → wing-inbox + ntfy).

notify() {
    local severity="$1" template="$2" context_json="$3"
    if [[ -z "${WING_EVENTS_HMAC_SECRET:-}" ]]; then
        echo "INFO: WING_EVENTS_HMAC_SECRET unset — skipping notification emit (result logged only)"
        return 0
    fi
    local body compact ts sig code
    body=$(jq -n \
        --arg sev "$severity" \
        --arg tpl "$template" \
        --arg run_id "$RUN_ID" \
        --arg tofu_dir "$TOFU_DIR" \
        --argjson ctx "$context_json" \
        '{severity: $sev, template: $tpl, context: $ctx,
          origin_plugin: "authentik-tofu-drift",
          actor_id: "plugin:authentik-tofu-drift",
          actor_action_id: $run_id,
          metadata: {tofu_dir: $tofu_dir, run_id: $run_id}}')
    # Canonical form (sort_keys + compact) so Bone's HMAC verifier matches —
    # Bone re-canonicalizes via json.dumps(separators=(',',':'), sort_keys=True)
    # before computing the expected signature (live 2026-05-17 401 incident).
    # -a and printf, both load-bearing: Bone re-serialises the parsed body with
    # Python json.dumps (ensure_ascii defaults TRUE), so a raw UTF-8 byte here
    # signs different bytes than Bone verifies; and `echo` expands the \n inside
    # a JSON string, which makes jq refuse the input and leaves this empty.
    compact=$(printf '%s' "$body" | jq -a --sort-keys -c .)
    ts=$(date +%s)
    sig=$(printf '%s.%s' "$ts" "$compact" \
          | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" \
          | awk '{print $NF}')   # openssl 3.x emits just <hex>; 1.x emits "(stdin)= <hex>"
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "X-Wing-Timestamp: $ts" \
        -H "X-Wing-Signature: $sig" \
        -H "Content-Type: application/json" \
        -d "$compact" \
        "$BONE_URL/api/v1/notifications" 2>&1 || echo "000")
    if [[ "$code" == "200" || "$code" == "201" ]]; then
        echo "INFO: notification emitted (severity=$severity, template=$template)"
    else
        echo "WARN: notification POST returned HTTP $code — drift result logged only" >&2
    fi
}

# ── Run the plan (read-only, lockless, watchdog-bounded) ─────────────────────

PLAN_LOG="$(mktemp /tmp/tofu-drift-XXXXXXXX.log)"
trap 'rm -f "$PLAN_LOG"' EXIT

cd "$TOFU_DIR"
echo "INFO: running read-only tofu plan in $TOFU_DIR (timeout=${TIMEOUT_S}s, run_id=$RUN_ID)"

# -detailed-exitcode: rc=0 no changes, rc=2 changes (drift), rc=1 error.
# -lock=false: see header — read-only, never blocks on / takes the state lock.
# Internal watchdog (portable: macOS ships no GNU `timeout`): SIGKILL the plan
# after TIMEOUT_S so the error-notify below still runs; Pulse's max_runtime_s
# (600s) remains the hard backstop. The orphaned `sleep` after a fast plan is
# harmless — it exits on its own.
set +e
"$TOFU_BIN" plan -input=false -no-color -detailed-exitcode -lock=false \
    >"$PLAN_LOG" 2>&1 &
PLAN_PID=$!
# stdout redirected too: if a platform leaves the sleep orphaned holding the
# inherited stdout pipe, Pulse's capture would block for the full TIMEOUT_S.
( sleep "$TIMEOUT_S" && kill -9 "$PLAN_PID" ) >/dev/null 2>&1 &
WATCHDOG_PID=$!
wait "$PLAN_PID"
PLAN_RC=$?
# Reap the watchdog quietly — without the trailing `wait`, bash prints a
# "Terminated" job notice into the Pulse-captured output on every clean run.
kill "$WATCHDOG_PID" 2>/dev/null
wait "$WATCHDOG_PID" 2>/dev/null
set -e

# ── Outcome handling ──────────────────────────────────────────────────────────

if [[ "$PLAN_RC" -eq 0 ]]; then
    echo "INFO: no drift — live Authentik tenant matches OpenTofu state"
    exit 0
fi

if [[ "$PLAN_RC" -eq 2 ]]; then
    # One-line resource-change summary, e.g. "Plan: 0 to add, 2 to change, 0 to destroy."
    SUMMARY="$(grep -E '^Plan: ' "$PLAN_LOG" | tail -n 1 || true)"
    if [[ -z "$SUMMARY" ]]; then
        SUMMARY="changes detected (no 'Plan:' summary line — see Pulse run log)"
    fi
    # Top drifted resources ("# <addr> will be updated in-place" lines).
    TOP_CHANGES_MD="$(grep -E '^[[:space:]]*# ' "$PLAN_LOG" \
        | sed -E 's/^[[:space:]]*#/-/' | head -n 5 || true)"
    echo "WARN: Authentik drifted from OpenTofu state — $SUMMARY"
    CTX=$(jq -n \
        --arg summary "$SUMMARY" \
        --arg tofu_dir "$TOFU_DIR" \
        --arg top "$TOP_CHANGES_MD" \
        '{summary: $summary, tofu_dir: $tofu_dir, top_changes_md: $top}')
    notify "medium" "drift_detected" "$CTX"
    exit 1
fi

# rc=1 (provider/API/config error) or >=128 (watchdog SIGKILL after timeout).
if [[ "$PLAN_RC" -ge 128 ]]; then
    ERROR_TAIL="tofu plan timed out after ${TIMEOUT_S}s (killed by watchdog)"
else
    ERROR_TAIL="$(tail -n 12 "$PLAN_LOG")"
fi
echo "ERROR: tofu plan failed (rc=$PLAN_RC): $ERROR_TAIL" >&2
CTX=$(jq -n \
    --arg tofu_dir "$TOFU_DIR" \
    --arg error_tail "$ERROR_TAIL" \
    '{tofu_dir: $tofu_dir, error_tail: $error_tail}')
notify "high" "plan_error" "$CTX"
exit 2
