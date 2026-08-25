#!/usr/bin/env bash
# =============================================================================
# run-scout.sh — operator-driven drift / visibility scan (Anatomy A9.4)
#
# Fires the scout agent's `drift-scan` Pulse job on demand. Scout reads
# the last 7 days of events + notifications + pulse_runs from wing.db,
# correlates with committed state, and reports anomalies via a markdown
# Drift report event + notification.
#
# Same shape as tools/run-phase5-ceremony.sh + tools/run-remediator.sh:
# pre-flight (Bone health + pulse_jobs row + Authentik token grant), env
# resolution from pulse_jobs.env_json, post-flight verifier, markdown
# report to ~/.nos/scout-report-<ts>.md.
#
# Scout's Pulse row is paused=1 by default. This script intentionally
# runs it OFF-schedule: drift detection is useful RIGHT AFTER something
# changes (post-blank, post-upgrade, post-incident), not on a fixed cron.
#
# Usage:
#   bash tools/run-scout.sh           # run the drift scan
#   bash tools/run-scout.sh --dry-run # pre-flight only
#
# Exit codes:
#   0 — scout exit 0 (zero drift signals — operations look steady)
#   1 — scout exit 1 (drift signals triggered — read the report)
#   2 — pre-flight failed
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:drift-scan"
DRY_RUN=0
REPORT_FILE="${SCOUT_REPORT_FILE:-${HOME}/.nos/scout-report-$(date +%Y%m%dT%H%M%S).md}"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown arg '$arg' (use --dry-run or --help)" >&2
            exit 2
            ;;
    esac
done

_die() { echo "ERROR: $*" >&2; exit 2; }

# THE secret-reference resolver (shared with the Pulse daemon — one
# implementation, N callers; see tools/lib/pulse-env.sh).
# shellcheck source=tools/lib/pulse-env.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/pulse-env.sh"

echo "── nOS scout — operator-driven drift scan ───────────────────────────"
echo "WING_DB: $WING_DB"
echo "Report:  $REPORT_FILE"
echo

for cmd in sqlite3 curl jq python3; do
    command -v "$cmd" >/dev/null || _die "missing required command: $cmd"
done

[[ -f "$WING_DB" ]] || _die "Wing DB not found at $WING_DB"

BONE_URL="${BONE_API_URL:-http://127.0.0.1:8099}"
BONE_HEALTH=$(curl -sS -o /dev/null -w "%{http_code}" "$BONE_URL/api/health" 2>/dev/null || echo "000")
[[ "$BONE_HEALTH" == "200" ]] || _die "Bone $BONE_URL/api/health returned $BONE_HEALTH"
echo "✓ Bone $BONE_URL/api/health → 200"

PULSE_JOB_ROW=$(sqlite3 -json "$WING_DB" \
    "SELECT id, command, args_json, env_json, paused FROM pulse_jobs WHERE id LIKE '$JOB_ID_PATTERN' LIMIT 1;" 2>/dev/null || true)
if [[ -z "$PULSE_JOB_ROW" || "$PULSE_JOB_ROW" == "[]" ]]; then
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — has the scout plugin/agent registration run? Re-run --tags anatomy.plugins after the agent profile lands in Wing."
fi
JOB_ID=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].id')
JOB_CMD=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].command')
JOB_ARGS_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].args_json')
JOB_ENV_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].env_json')
# Resolve `secret:<name>` references NOW — the pre-flight below reads tokens
# out of this env and the agent subprocess inherits it. Refusal here is a
# pre-flight failure, not a burned LLM run; the literal is never exported.
JOB_ENV_JSON=$(printf '%s' "$JOB_ENV_JSON" | resolve_pulse_env_json) \
    || _die "secret-reference resolution failed for $JOB_ID (see message above; store: ~/.nos/secrets.yml — nothing was exported)"
JOB_PAUSED=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].paused')

[[ -x "$JOB_CMD" ]] || _die "registered command is not executable: $JOB_CMD"
echo "✓ pulse_jobs row found: $JOB_ID (paused=$JOB_PAUSED — manual invocation overrides)"

# Token-grant pre-flight (shared: tools/lib/pulse-env.sh). Liveness alone was
# this pre-flight's signature defect — the server answered 200 while THIS
# client's credential died on invalid_grant moments later. Now the check IS
# a client_credentials grant for the job's own client, and it fails closed.
pulse_token_preflight "$JOB_ENV_JSON" \
    || _die "Authentik token-grant pre-flight failed (see message above)"

# Quick peek at events in the 7-day window so the operator knows the
# analysis window has something to look at.
RECENT_EVENTS=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE ts >= datetime('now','-7 days');" 2>/dev/null || echo "?")
echo "✓ Events in 7-day window: $RECENT_EVENTS"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would invoke:"
    echo "  command: $JOB_CMD"
    echo "  args:    $JOB_ARGS_JSON"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

PRE_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'scout';")
PRE_RUN_NOTIF_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM notifications WHERE origin_agent = 'scout';")
RUN_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo
echo "── Firing scout (pre: $PRE_RUN_REPORT_COUNT scout events, $PRE_RUN_NOTIF_COUNT notifications) ──"
echo

ENV_FILE=$(mktemp /tmp/scout-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do
        JOB_ARGS_ARR+=("$line")
    done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="scout-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/scout-output-XXXXX)
RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo
echo "── Scan exit: $RUN_EXIT ──"
echo

POST_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'scout';")
POST_RUN_NOTIF_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM notifications WHERE origin_agent = 'scout';")
EVENT_DELTA=$((POST_RUN_REPORT_COUNT - PRE_RUN_REPORT_COUNT))
NOTIF_DELTA=$((POST_RUN_NOTIF_COUNT - PRE_RUN_NOTIF_COUNT))

LATEST_ACTION_ID=$(sqlite3 -json "$WING_DB" \
    "SELECT actor_action_id FROM events WHERE source = 'scout' AND ts >= '$RUN_START_ISO' ORDER BY id ASC LIMIT 1;" \
    | jq -r '.[0].actor_action_id // ""')

REPORT_JSON=""
if [[ -n "$LATEST_ACTION_ID" ]]; then
    REPORT_JSON=$(sqlite3 -json "$WING_DB" \
        "SELECT type, ts, result_json FROM events WHERE actor_action_id = '$LATEST_ACTION_ID' ORDER BY id ASC;")
fi

{
    echo "# nOS scout report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**scan exit:** \`$RUN_EXIT\`"
    echo "**actor_action_id:** \`${LATEST_ACTION_ID:-not-found}\`"
    echo "**events analyzed (7-day window):** \`$RECENT_EVENTS\`"
    echo
    echo "## Pre-flight"
    echo "- Bone /api/health → 200 ✓"
    echo "- pulse_jobs row → \`$JOB_ID\` ✓"
    [[ -n "$AK_URL" ]] && echo "- Authentik $AK_URL → reachable ✓"
    echo
    echo "## Post-flight"
    echo "- scout events written: $EVENT_DELTA (was $PRE_RUN_REPORT_COUNT → now $POST_RUN_REPORT_COUNT)"
    echo "- scout notifications: $NOTIF_DELTA (was $PRE_RUN_NOTIF_COUNT → now $POST_RUN_NOTIF_COUNT)"
    echo
    if [[ -n "$REPORT_JSON" && "$REPORT_JSON" != "[]" ]]; then
        echo "## Event lineage (actor_action_id = \`$LATEST_ACTION_ID\`)"
        echo
        echo "$REPORT_JSON" | jq -r '.[] | "- **\(.type)** @ \(.ts)"'
        echo
        REPORT_MD=$(echo "$REPORT_JSON" | jq -r '.[] | select(.type == "conductor_report") | .result_json | fromjson | .report_markdown // ""' 2>/dev/null || echo "")
        if [[ -n "$REPORT_MD" ]]; then
            echo "## Scout's own report"
            echo
            echo "$REPORT_MD"
            echo
        fi
    fi
    echo "## Scan stdout/stderr"
    echo
    echo '```'
    tail -60 "$OUTPUT_FILE"
    echo '```'
    echo
    if [[ "$RUN_EXIT" -eq 0 ]]; then
        echo "## Verdict"
        echo
        echo "**GREEN** — scan exit 0. No drift signals; operations look steady."
    elif [[ "$RUN_EXIT" -eq 1 ]]; then
        echo "## Verdict"
        echo
        echo "**REVIEW** — scan exit 1: drift signal(s) triggered."
        echo
        echo "1. Read the \`Scout's own report\` above (Detected drift section)."
        echo "2. Answer each operator-question (yes/no) — was the drift intentional?"
        echo "3. If unintentional: trigger remediator (\`bash tools/run-remediator.sh\`) or hand-investigate."
    else
        echo "## Verdict"
        echo
        echo "**RED** — scan failed at exit \`$RUN_EXIT\` (env/auth/Wing error)."
        echo "Read \`Scan stdout/stderr\` for the failing step."
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"

echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
