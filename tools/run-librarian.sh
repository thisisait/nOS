#!/usr/bin/env bash
# =============================================================================
# run-librarian.sh — operator-driven knowledge judgment (cortex Layer 2)
#
# Fires the librarian agent's `judge-lint-queue` Pulse job on demand. Same
# shape as tools/run-scout.sh: pre-flight (KEAP health + intake peek +
# pulse_jobs row + Authentik liveness), env resolution from
# pulse_jobs.env_json, post-flight verifier (events + verdict count),
# markdown report to ~/.nos/librarian-report-<ts>.md.
#
# The librarian's Pulse row is paused=1 by default (on-demand doctrine —
# see files/anatomy/agents/librarian.yml). Judgment makes sense right after
# the nightly keap-lint filled the intake, or after a curation batch — not
# on a fixed cron.
#
# Usage:
#   bash tools/run-librarian.sh           # judge the intake queue
#   bash tools/run-librarian.sh --dry-run # pre-flight only
#
# Exit codes:
#   0 — queue empty or everything judged fine
#   1 — duplicate/contradiction verdict(s) issued — read the report
#   2 — pre-flight failed (missing dep / unreachable service / no job row)
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:judge-lint-queue"
DRY_RUN=0
REPORT_FILE="${LIBRARIAN_REPORT_FILE:-${HOME}/.nos/librarian-report-$(date +%Y%m%dT%H%M%S).md}"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,23p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown arg '$arg' (use --dry-run or --help)" >&2
            exit 2
            ;;
    esac
done

_die() { echo "ERROR: $*" >&2; exit 2; }

echo "── nOS librarian — operator-driven knowledge judgment ───────────────"
echo "WING_DB: $WING_DB"
echo "Report:  $REPORT_FILE"
echo

for cmd in sqlite3 curl jq python3; do
    command -v "$cmd" >/dev/null || _die "missing required command: $cmd"
done

[[ -f "$WING_DB" ]] || _die "Wing DB not found at $WING_DB"

PULSE_JOB_ROW=$(sqlite3 -json "$WING_DB" \
    "SELECT id, command, args_json, env_json, paused FROM pulse_jobs WHERE id LIKE '$JOB_ID_PATTERN' LIMIT 1;" 2>/dev/null || true)
if [[ -z "$PULSE_JOB_ROW" || "$PULSE_JOB_ROW" == "[]" ]]; then
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — re-run the wing tag after the librarian profile lands."
fi
JOB_ID=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].id')
JOB_CMD=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].command')
JOB_ARGS_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].args_json')
JOB_ENV_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].env_json')
JOB_PAUSED=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].paused')

[[ -x "$JOB_CMD" ]] || _die "registered command is not executable: $JOB_CMD"
echo "✓ pulse_jobs row found: $JOB_ID (paused=$JOB_PAUSED — manual invocation overrides)"

# KEAP pre-flight: health + intake size (so the operator knows whether a
# run has anything to judge before burning an LLM session).
KEAP_URL=$(echo "$JOB_ENV_JSON" | jq -r '.KEAP_API_URL // "http://127.0.0.1:8091"')
KEAP_RO=$(echo "$JOB_ENV_JSON" | jq -r '.KEAP_AGENT_TOKEN_RO // ""')
KEAP_HEALTH=$(curl -sS -o /dev/null -w "%{http_code}" "$KEAP_URL/agent/v1/health" 2>/dev/null || echo "000")
[[ "$KEAP_HEALTH" == "200" ]] || _die "KEAP $KEAP_URL/agent/v1/health returned $KEAP_HEALTH"
echo "✓ KEAP $KEAP_URL/agent/v1/health → 200"

INTAKE_COUNT=0
for check in overlap-review near-duplicate; do
    N=$(curl -sS -H "Authorization: Bearer $KEAP_RO" \
        "$KEAP_URL/agent/v1/lint?check=$check&unjudged=1&limit=500" 2>/dev/null \
        | jq -r '.data.findings | length' 2>/dev/null || echo 0)
    INTAKE_COUNT=$((INTAKE_COUNT + N))
done
echo "✓ Intake queue (unjudged overlap/duplicate findings): $INTAKE_COUNT"

AK_URL=$(echo "$JOB_ENV_JSON" | jq -r '.NOS_AUTHENTIK_URL // ""')
if [[ -n "$AK_URL" ]]; then
    AK_HEALTH=$(curl -sS -k -o /dev/null -w "%{http_code}" "$AK_URL/-/health/live/" 2>/dev/null || echo "000")
    if [[ "$AK_HEALTH" == "200" || "$AK_HEALTH" == "204" ]]; then
        echo "✓ Authentik $AK_URL liveness → $AK_HEALTH"
    else
        _die "Authentik $AK_URL liveness returned $AK_HEALTH"
    fi
fi

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would invoke:"
    echo "  command: $JOB_CMD"
    echo "  intake:  $INTAKE_COUNT finding(s)"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

if [[ "$INTAKE_COUNT" -eq 0 ]]; then
    echo
    echo "Intake queue is EMPTY — nothing to judge; not burning an agent run."
    echo "(Run tools/nos-stacks.sh keap + the keap-lint job first if you expected findings.)"
    exit 0
fi

PRE_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'librarian';")
RUN_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo
echo "── Firing librarian (pre: $PRE_RUN_REPORT_COUNT librarian events, intake $INTAKE_COUNT) ──"
echo

ENV_FILE=$(mktemp /tmp/librarian-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do
        JOB_ARGS_ARR+=("$line")
    done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="librarian-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/librarian-output-XXXXX)
RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo
echo "── Judgment exit: $RUN_EXIT ──"
echo

POST_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'librarian';")
EVENT_DELTA=$((POST_RUN_REPORT_COUNT - PRE_RUN_REPORT_COUNT))

REMAINING=0
for check in overlap-review near-duplicate; do
    N=$(curl -sS -H "Authorization: Bearer $KEAP_RO" \
        "$KEAP_URL/agent/v1/lint?check=$check&unjudged=1&limit=500" 2>/dev/null \
        | jq -r '.data.findings | length' 2>/dev/null || echo 0)
    REMAINING=$((REMAINING + N))
done
JUDGED=$((INTAKE_COUNT - REMAINING))

LATEST_ACTION_ID=$(sqlite3 -json "$WING_DB" \
    "SELECT actor_action_id FROM events WHERE source = 'librarian' AND ts >= '$RUN_START_ISO' ORDER BY id ASC LIMIT 1;" \
    | jq -r '.[0].actor_action_id // ""')

REPORT_MD=""
if [[ -n "$LATEST_ACTION_ID" ]]; then
    REPORT_MD=$(sqlite3 -json "$WING_DB" \
        "SELECT result_json FROM events WHERE actor_action_id = '$LATEST_ACTION_ID' AND type = 'conductor_report' ORDER BY id DESC LIMIT 1;" \
        | jq -r '.[0].result_json | fromjson | .report_markdown // ""' 2>/dev/null || echo "")
fi

{
    echo "# nOS librarian report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**judgment exit:** \`$RUN_EXIT\`"
    echo "**intake:** \`$INTAKE_COUNT\` → **judged:** \`$JUDGED\` → **remaining unjudged:** \`$REMAINING\`"
    echo "**librarian events written:** \`$EVENT_DELTA\`"
    echo
    if [[ -n "$REPORT_MD" ]]; then
        echo "## Librarian's own report"
        echo
        echo "$REPORT_MD"
        echo
    fi
    echo "## Run stdout/stderr"
    echo
    echo '```'
    tail -60 "$OUTPUT_FILE"
    echo '```'
    echo
    echo "## Verdict"
    echo
    if [[ "$RUN_EXIT" -eq 0 ]]; then
        echo "**GREEN** — queue judged; nothing escalated."
    elif [[ "$RUN_EXIT" -eq 1 ]]; then
        echo "**REVIEW** — verdict(s) or proposal(s) await the moderator."
        echo
        echo "1. Read \`Librarian's own report\` → Escalations + Taxonomy."
        echo "2. Escalated findings sit in KEAP Admin › Lint at medium/high."
        echo "3. Merge duplicates / resolve contradictions in the Admin CMS."
        echo "4. Promotion + node proposals sit in KEAP Admin › Moderation."
    else
        echo "**RED** — run failed at exit \`$RUN_EXIT\` (env/auth error). Read stdout above."
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"

echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
