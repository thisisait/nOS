#!/usr/bin/env bash
# =============================================================================
# run-librarian.sh — operator-driven knowledge judgment (cortex Layer 2)
#
# Fires the librarian agent's `judge-lint-queue` Pulse job on demand. The
# shared launcher shape: pre-flight (KEAP health + intake peek +
# pulse_jobs row + Authentik token grant), env resolution from
# pulse_jobs.env_json, post-flight verifier (events + verdict count),
# markdown report to ~/.nos/librarian-report-<ts>.md.
#
# The librarian's Pulse row is paused=1 by default (on-demand doctrine —
# see files/anatomy/agents/librarian.yml). Judgment makes sense right after
# the nightly keap-lint filled the intake, or after a curation batch — not
# on a fixed cron.
#
# Usage:
#   bash tools/run-librarian.sh            # judge the lint intake queue
#   bash tools/run-librarian.sh --describe # K1: one taxonomy-describe batch
#   bash tools/run-librarian.sh --brief    # one taxonomy-brief batch (root)
#   bash tools/run-librarian.sh --dry-run  # pre-flight only (any mode)
#
# Exit codes:
#   0 — queue empty or everything judged fine
#   1 — verdict(s)/proposal(s) await the moderator — read the report
#   2 — pre-flight failed (missing dep / unreachable service / no job row)
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
MODE="judge"
JOB_ID_PATTERN="%:judge-lint-queue"
DRY_RUN=0
REPORT_FILE="${LIBRARIAN_REPORT_FILE:-${HOME}/.nos/librarian-report-$(date +%Y%m%dT%H%M%S).md}"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --describe)
            MODE="describe"
            JOB_ID_PATTERN="%:describe-taxonomy"
            ;;
        --brief)
            MODE="brief"
            JOB_ID_PATTERN="%:brief-taxonomy"
            ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown arg '$arg' (use --describe, --brief, --dry-run or --help)" >&2
            exit 2
            ;;
    esac
done

_die() { echo "ERROR: $*" >&2; exit 2; }

# THE secret-reference resolver (shared with the Pulse daemon — one
# implementation, N callers; see tools/lib/pulse-env.sh).
# shellcheck source=tools/lib/pulse-env.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/pulse-env.sh"

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
# Resolve `secret:<name>` references NOW — the pre-flight below reads tokens
# out of this env and the agent subprocess inherits it. Refusal here is a
# pre-flight failure, not a burned LLM run; the literal is never exported.
JOB_ENV_JSON=$(printf '%s' "$JOB_ENV_JSON" | resolve_pulse_env_json) \
    || _die "secret-reference resolution failed for $JOB_ID (see message above; store: ~/.nos/secrets.yml — nothing was exported)"
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

# Mode-aware intake size: judge = unjudged lint findings; describe = nodes
# still lacking a curated description (K1). Reused for the post-flight delta.
# Returns a bare integer on success, or the literal "ERR" when KEAP answers
# with a non-numeric body — an auth failure ({"error":…} → jq prints "null")
# or an older deployment missing the endpoint (HTML 404). `// empty` + the
# numeric guard turn those into "ERR" so the caller can _die cleanly at
# pre-flight instead of a false-green "backlog EMPTY" or a set -u crash.
_intake_count() {
    local total=0 n
    if [[ "$MODE" == "describe" ]]; then
        n=$(curl -sS -H "Authorization: Bearer $KEAP_RO" \
            "$KEAP_URL/agent/v1/taxonomy/describe/pending?limit=1" 2>/dev/null \
            | jq -r '.data.total // empty' 2>/dev/null || true)
        [[ "$n" =~ ^[0-9]+$ ]] || { echo "ERR"; return; }
        total=$n
    elif [[ "$MODE" == "brief" ]]; then
        # Scope must match the job task's maxLevel (full sweep = 9).
        n=$(curl -sS -H "Authorization: Bearer $KEAP_RO" \
            "$KEAP_URL/agent/v1/taxonomy/brief/pending?limit=1&maxLevel=9" 2>/dev/null \
            | jq -r '.data.total // empty' 2>/dev/null || true)
        [[ "$n" =~ ^[0-9]+$ ]] || { echo "ERR"; return; }
        total=$n
    else
        for check in overlap-review near-duplicate; do
            n=$(curl -sS -H "Authorization: Bearer $KEAP_RO" \
                "$KEAP_URL/agent/v1/lint?check=$check&unjudged=1&limit=500" 2>/dev/null \
                | jq -r '.data.findings | length' 2>/dev/null || true)
            [[ "$n" =~ ^[0-9]+$ ]] || { echo "ERR"; return; }
            total=$((total + n))
        done
    fi
    echo "$total"
}

INTAKE_COUNT=$(_intake_count)
[[ "$INTAKE_COUNT" =~ ^[0-9]+$ ]] || _die "KEAP intake count unreadable — check $KEAP_URL reachability, the $MODE endpoint, and KEAP_AGENT_TOKEN_RO (auth 401/403 returns a non-numeric body)."
case "$MODE" in
    describe) echo "✓ Describe backlog (nodes without a load-bearing description): $INTAKE_COUNT" ;;
    brief)    echo "✓ Brief backlog (nodes without an article, full maxLevel=9 sweep): $INTAKE_COUNT" ;;
    *)        echo "✓ Intake queue (unjudged overlap/duplicate findings): $INTAKE_COUNT" ;;
esac

# Token-grant pre-flight (shared: tools/lib/pulse-env.sh). Liveness alone was
# this pre-flight's signature defect — the server answered 200 while THIS
# client's credential died on invalid_grant moments later. Now the check IS
# a client_credentials grant for the job's own client, and it fails closed.
pulse_token_preflight "$JOB_ENV_JSON" \
    || _die "Authentik token-grant pre-flight failed (see message above)"

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
    if [[ "$MODE" == "describe" ]]; then
        echo "Describe backlog is EMPTY — every node carries a description; not burning an agent run."
    elif [[ "$MODE" == "brief" ]]; then
        echo "Brief backlog is EMPTY — the root taxonomy carries its articles; not burning an agent run."
    else
        echo "Intake queue is EMPTY — nothing to judge; not burning an agent run."
        echo "(Run tools/nos-stacks.sh keap + the keap-lint job first if you expected findings.)"
    fi
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
trap 'rm -f "$ENV_FILE" "$OUTPUT_FILE"' EXIT
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

# Post-flight: the LLM run is already spent, so a transient read failure must
# NOT crash before the report is written — degrade the delta to "?" instead.
REMAINING=$(_intake_count)
if [[ "$REMAINING" =~ ^[0-9]+$ ]]; then
    JUDGED=$((INTAKE_COUNT - REMAINING))
else
    REMAINING="?"
    JUDGED="?"
fi

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
    if [[ "$MODE" == "describe" || "$MODE" == "brief" ]]; then
        echo "**backlog:** \`$INTAKE_COUNT\` → **proposed this run:** \`$JUDGED\` → **still pending:** \`$REMAINING\`"
    else
        echo "**intake:** \`$INTAKE_COUNT\` → **judged:** \`$JUDGED\` → **remaining unjudged:** \`$REMAINING\`"
    fi
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
    elif [[ "$RUN_EXIT" -eq 1 && ( "$MODE" == "describe" || "$MODE" == "brief" ) ]]; then
        echo "**REVIEW** — $MODE batch proposed (the normal outcome)."
        echo
        echo "1. KEAP Admin › Moderation → bulk-approve the $MODE batch."
        echo "2. Next keap-embed-sync re-embeds the approved nodes."
        echo "3. Re-run tools/run-librarian.sh --$MODE for the next batch."
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
