#!/usr/bin/env bash
# =============================================================================
# run-remediator.sh — operator-driven remediator triage (Anatomy A9.3)
#
# Fires the remediator agent's `triage-open-findings` Pulse job on demand.
# Same shape as tools/run-phase5-ceremony.sh: pre-flight (Bone health +
# pulse_jobs row + Authentik liveness), env resolution from
# pulse_jobs.env_json, post-flight verifier (events + remediation report +
# notification), markdown report to ~/.nos/remediator-report-<ts>.md.
#
# The remediator's Pulse row is paused=1 by default (see
# files/anatomy/agents/remediator.yml — schedule is a placeholder). This
# script intentionally runs it OFF-schedule: triage should happen right
# after gitleaks emits findings, not on a fixed cron.
#
# Usage:
#   bash tools/run-remediator.sh           # run the triage
#   bash tools/run-remediator.sh --dry-run # pre-flight only
#
# Exit codes:
#   0 — triage exit 0 (no open findings)
#   1 — triage exit 1 (findings need operator review — read the report)
#   2 — pre-flight failed (missing dep / unreachable service / no job row)
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:triage-open-findings"
DRY_RUN=0
REPORT_FILE="${REMEDIATOR_REPORT_FILE:-${HOME}/.nos/remediator-report-$(date +%Y%m%dT%H%M%S).md}"

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

echo "── nOS remediator — operator-driven triage ──────────────────────────"
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
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — has the remediator plugin/agent registration run? Re-run --tags anatomy.plugins after the agent profile lands in Wing."
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

AK_URL=$(echo "$JOB_ENV_JSON" | jq -r '.NOS_AUTHENTIK_URL // ""')
if [[ -n "$AK_URL" ]]; then
    AK_HEALTH=$(curl -sS -k -o /dev/null -w "%{http_code}" "$AK_URL/-/health/live/" 2>/dev/null || echo "000")
    if [[ "$AK_HEALTH" == "200" || "$AK_HEALTH" == "204" ]]; then
        echo "✓ Authentik $AK_URL liveness → $AK_HEALTH"
    else
        _die "Authentik $AK_URL liveness returned $AK_HEALTH (client_credentials mint will fail)"
    fi
fi

# Quick peek at open findings (helps operator decide whether to even fire).
OPEN_FINDINGS=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM gitleaks_findings WHERE resolved_at IS NULL;" 2>/dev/null || echo "?")
echo "✓ Open gitleaks_findings to triage: $OPEN_FINDINGS"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would invoke:"
    echo "  command: $JOB_CMD"
    echo "  args:    $JOB_ARGS_JSON"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

PRE_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'remediator';")
PRE_RUN_NOTIF_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM notifications WHERE origin_agent = 'remediator';")
RUN_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo
echo "── Firing remediator (pre: $PRE_RUN_REPORT_COUNT remediator events, $PRE_RUN_NOTIF_COUNT notifications) ──"
echo

ENV_FILE=$(mktemp /tmp/remediator-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do
        JOB_ARGS_ARR+=("$line")
    done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="remediator-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/remediator-output-XXXXX)
RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo
echo "── Triage exit: $RUN_EXIT ──"
echo

POST_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'remediator';")
POST_RUN_NOTIF_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM notifications WHERE origin_agent = 'remediator';")
EVENT_DELTA=$((POST_RUN_REPORT_COUNT - PRE_RUN_REPORT_COUNT))
NOTIF_DELTA=$((POST_RUN_NOTIF_COUNT - PRE_RUN_NOTIF_COUNT))

LATEST_ACTION_ID=$(sqlite3 -json "$WING_DB" \
    "SELECT actor_action_id FROM events WHERE source = 'remediator' AND ts >= '$RUN_START_ISO' ORDER BY id ASC LIMIT 1;" \
    | jq -r '.[0].actor_action_id // ""')

REPORT_JSON=""
if [[ -n "$LATEST_ACTION_ID" ]]; then
    REPORT_JSON=$(sqlite3 -json "$WING_DB" \
        "SELECT type, ts, result_json FROM events WHERE actor_action_id = '$LATEST_ACTION_ID' ORDER BY id ASC;")
fi

{
    echo "# nOS remediator report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**triage exit:** \`$RUN_EXIT\`"
    echo "**actor_action_id:** \`${LATEST_ACTION_ID:-not-found}\`"
    echo "**open findings at start:** \`$OPEN_FINDINGS\`"
    echo
    echo "## Pre-flight"
    echo "- Bone /api/health → 200 ✓"
    echo "- pulse_jobs row → \`$JOB_ID\` ✓"
    [[ -n "$AK_URL" ]] && echo "- Authentik $AK_URL → reachable ✓"
    echo
    echo "## Post-flight"
    echo "- remediator events written: $EVENT_DELTA (was $PRE_RUN_REPORT_COUNT → now $POST_RUN_REPORT_COUNT)"
    echo "- remediator notifications: $NOTIF_DELTA (was $PRE_RUN_NOTIF_COUNT → now $POST_RUN_NOTIF_COUNT)"
    echo
    if [[ -n "$REPORT_JSON" && "$REPORT_JSON" != "[]" ]]; then
        echo "## Event lineage (actor_action_id = \`$LATEST_ACTION_ID\`)"
        echo
        echo "$REPORT_JSON" | jq -r '.[] | "- **\(.type)** @ \(.ts)"'
        echo
        # Extract the markdown report body from the conductor_report row.
        REPORT_MD=$(echo "$REPORT_JSON" | jq -r '.[] | select(.type == "conductor_report") | .result_json | fromjson | .report_markdown // ""' 2>/dev/null || echo "")
        if [[ -n "$REPORT_MD" ]]; then
            echo "## Remediator's own report"
            echo
            echo "$REPORT_MD"
            echo
        fi
    fi
    echo "## Triage stdout/stderr"
    echo
    echo '```'
    tail -60 "$OUTPUT_FILE"
    echo '```'
    echo
    if [[ "$RUN_EXIT" -eq 0 ]]; then
        echo "## Verdict"
        echo
        echo "**GREEN** — triage exit 0 (typically: no open findings)."
    elif [[ "$RUN_EXIT" -eq 1 ]]; then
        echo "## Verdict"
        echo
        echo "**REVIEW** — triage exit 1: $OPEN_FINDINGS finding(s) need operator attention."
        echo
        echo "1. Read the \`Remediator's own report\` above (markdown table of findings + suggested fixes)."
        echo "2. For each finding to resolve, click Wing /inbox → Secret Findings → Mark Resolved."
        echo "3. Re-run \`bash tools/run-remediator.sh\` after applying fixes to verify clean."
    else
        echo "## Verdict"
        echo
        echo "**RED** — triage failed at exit \`$RUN_EXIT\` (env/auth/Wing error)."
        echo "Read \`Triage stdout/stderr\` for the failing step."
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"

echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
