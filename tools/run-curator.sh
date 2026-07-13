#!/usr/bin/env bash
# =============================================================================
# run-curator.sh — operator-driven taxonomy reconciliation (cortex Layer 2)
#
# Fires the curator agent's `curator-sweep` Pulse job on demand. Same shape
# as tools/run-librarian.sh: pre-flight (KEAP health + frontier peek +
# pulse_jobs row + Authentik liveness), env resolution from
# pulse_jobs.env_json, post-flight verifier (events + frontier delta),
# markdown report to ~/.nos/curator-report-<ts>.md.
#
# The curator's Pulse row is paused=1 by default (on-demand doctrine — see
# files/anatomy/agents/curator.yml). A sweep makes sense after the nightly
# keap-embed-sync + keap-lint, or after a librarian curation batch — not on
# a fixed cron while it is a P0 pilot.
#
# P0: the curator sweeps the votable zone (level >= 3), lints each node's
# description, and PROPOSES rewrites into the moderation panel. Propose-only;
# nothing auto-applies (docs/plans/keap-curator-agent.md).
#
# Usage:
#   bash tools/run-curator.sh            # sweep one frontier batch
#   bash tools/run-curator.sh --dry-run  # pre-flight only
#
# Exit codes:
#   0 — sweep done; any rewrite proposals await the moderator (routine)
#   1 — a structural finding awaits operator review — read the report
#   2 — pre-flight failed (missing dep / unreachable service / no job row)
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:curator-sweep"
DRY_RUN=0
REPORT_FILE="${CURATOR_REPORT_FILE:-${HOME}/.nos/curator-report-$(date +%Y%m%dT%H%M%S).md}"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,28p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown arg '$arg' (use --dry-run or --help)" >&2
            exit 2
            ;;
    esac
done

_die() { echo "ERROR: $*" >&2; exit 2; }

echo "── nOS curator — operator-driven taxonomy reconciliation ────────────"
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
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — re-run the wing tag after the curator profile lands."
fi
JOB_ID=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].id')
JOB_CMD=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].command')
JOB_ARGS_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].args_json')
JOB_ENV_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].env_json')
JOB_PAUSED=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].paused')

[[ -x "$JOB_CMD" ]] || _die "registered command is not executable: $JOB_CMD"
echo "✓ pulse_jobs row found: $JOB_ID (paused=$JOB_PAUSED — manual invocation overrides)"

# KEAP pre-flight: health + frontier size (so the operator knows whether a
# run has anything to sweep before burning an LLM session).
KEAP_URL=$(echo "$JOB_ENV_JSON" | jq -r '.KEAP_API_URL // "http://127.0.0.1:8091"')
KEAP_RO=$(echo "$JOB_ENV_JSON" | jq -r '.KEAP_AGENT_TOKEN_RO // ""')
KEAP_HEALTH=$(curl -sS -o /dev/null -w "%{http_code}" "$KEAP_URL/agent/v1/health" 2>/dev/null || echo "000")
[[ "$KEAP_HEALTH" == "200" ]] || _die "KEAP $KEAP_URL/agent/v1/health returned $KEAP_HEALTH"
echo "✓ KEAP $KEAP_URL/agent/v1/health → 200"

# Frontier size: eligible nodes (level >= 3, cooldown-skipped). Returns a bare
# integer on success, or "ERR" when KEAP answers with a non-numeric body (auth
# failure or an older deployment missing the endpoint) so we _die at pre-flight
# instead of a false-green or a set -u crash.
_frontier_count() {
    local n
    n=$(curl -sS -H "Authorization: Bearer $KEAP_RO" \
        "$KEAP_URL/agent/v1/curator/frontier?minLevel=3&limit=1" 2>/dev/null \
        | jq -r '.data.total // empty' 2>/dev/null || true)
    [[ "$n" =~ ^[0-9]+$ ]] || { echo "ERR"; return; }
    echo "$n"
}

INTAKE_COUNT=$(_frontier_count)
[[ "$INTAKE_COUNT" =~ ^[0-9]+$ ]] || _die "KEAP frontier count unreadable — check $KEAP_URL reachability, the /agent/v1/curator/frontier endpoint, and KEAP_AGENT_TOKEN_RO (auth 401/403 returns a non-numeric body)."
echo "✓ Frontier (nodes L>=3 eligible for a sweep, cooldown-skipped): $INTAKE_COUNT"

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
    echo "  frontier: $INTAKE_COUNT node(s)"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

if [[ "$INTAKE_COUNT" -eq 0 ]]; then
    echo
    echo "Frontier is EMPTY — every L>=3 node was swept recently and is unchanged; not burning an agent run."
    echo "(The cooldown window has converged. Re-run after new nodes land or descriptions change.)"
    exit 0
fi

PRE_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'curator';")
RUN_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo
echo "── Firing curator (pre: $PRE_RUN_REPORT_COUNT curator events, frontier $INTAKE_COUNT) ──"
echo

ENV_FILE=$(mktemp /tmp/curator-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do
        JOB_ARGS_ARR+=("$line")
    done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="curator-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/curator-output-XXXXX)
trap 'rm -f "$ENV_FILE" "$OUTPUT_FILE"' EXIT
RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo
echo "── Sweep exit: $RUN_EXIT ──"
echo

POST_RUN_REPORT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'curator';")
EVENT_DELTA=$((POST_RUN_REPORT_COUNT - PRE_RUN_REPORT_COUNT))

# Post-flight: the LLM run is already spent, so a transient read failure must
# NOT crash before the report is written — degrade the delta to "?" instead.
REMAINING=$(_frontier_count)
if [[ "$REMAINING" =~ ^[0-9]+$ ]]; then
    SWEPT=$((INTAKE_COUNT - REMAINING))
else
    REMAINING="?"
    SWEPT="?"
fi

LATEST_ACTION_ID=$(sqlite3 -json "$WING_DB" \
    "SELECT actor_action_id FROM events WHERE source = 'curator' AND ts >= '$RUN_START_ISO' ORDER BY id ASC LIMIT 1;" \
    | jq -r '.[0].actor_action_id // ""')

REPORT_MD=""
if [[ -n "$LATEST_ACTION_ID" ]]; then
    REPORT_MD=$(sqlite3 -json "$WING_DB" \
        "SELECT result_json FROM events WHERE actor_action_id = '$LATEST_ACTION_ID' AND type = 'conductor_report' ORDER BY id DESC LIMIT 1;" \
        | jq -r '.[0].result_json | fromjson | .report_markdown // ""' 2>/dev/null || echo "")
fi

{
    echo "# nOS curator report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**sweep exit:** \`$RUN_EXIT\`"
    echo "**frontier:** \`$INTAKE_COUNT\` → **swept this run:** \`$SWEPT\` → **still eligible:** \`$REMAINING\`"
    echo "**curator events written:** \`$EVENT_DELTA\`"
    echo
    if [[ -n "$REPORT_MD" ]]; then
        echo "## Curator's own report"
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
        echo "**GREEN** — frontier swept; any description rewrites await moderation."
        echo
        echo "1. KEAP Admin › Moderace → review the desc proposals (proposed_by=agent:curator)."
        echo "2. Next keap-embed-sync re-embeds the approved nodes."
        echo "3. Re-run tools/run-curator.sh for the next frontier batch."
    elif [[ "$RUN_EXIT" -eq 1 ]]; then
        echo "**REVIEW** — a structural finding awaits the operator."
        echo
        echo "1. Read \`Curator's own report\` → the flagged structural finding."
        echo "2. P0 cannot propose the fix (node-edit/relation seams land in P1)."
        echo "3. Triage manually in the Admin CMS; the desc proposals still sit in Moderace."
    else
        echo "**RED** — run failed at exit \`$RUN_EXIT\` (env/auth error). Read stdout above."
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"

echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
