#!/usr/bin/env bash
# =============================================================================
# run-surveyor.sh — operator-driven surface survey (Anatomy A20)
#
# Fires the surveyor agent's `surface-survey` Pulse job on demand. The
# surveyor walks the estate and reports which of it deserves a control
# surface: what changes, what a person decides on, and what is decided on
# regularly while being visible nowhere.
#
# Same shape as tools/run-scout.sh and tools/run-remediator.sh — and the
# sameness is the point. The env comes from `pulse_jobs.env_json`, whose
# `secret:<name>` references are resolved by the ONE shared resolver in
# tools/lib/pulse-env.sh. A caller that builds its own environment instead
# exports the literal `secret:agent_surveyor_client_secret` and dies on an
# Authentik `invalid_grant` that says nothing about references — measured
# 2026-08-17, invoking pulse-run-agent.sh directly.
#
# The job row is paused by design; manual invocation overrides that. The
# surveyor is read-only and proposes only: it never renders a page, edits a
# ruling or opens a route.
#
# Usage:
#   bash tools/run-surveyor.sh            # run the survey
#   bash tools/run-surveyor.sh --dry-run  # pre-flight only, nothing spent
#
# Exit codes:
#   0 — survey completed (report written; findings live in the body)
#   2 — pre-flight failed, or the agent errored
# =============================================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:surface-survey"
DRY_RUN=0
REPORT_FILE="${SURVEYOR_REPORT_FILE:-${HOME}/.nos/surveyor-report-$(date +%Y%m%dT%H%M%S).md}"

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

# THE secret-reference resolver, shared with the Pulse daemon — one
# implementation, N callers. Never re-implement it here.
# shellcheck source=tools/lib/pulse-env.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/pulse-env.sh"

echo "── nOS surveyor — operator-driven surface survey ────────────────────"
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
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — has the surveyor profile reached Wing? Run: tools/nos-stacks.sh wing"
fi
JOB_ID=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].id')
JOB_CMD=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].command')
JOB_ARGS_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].args_json')
JOB_ENV_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].env_json')
# Resolve `secret:<name>` NOW. Refusal here is a pre-flight failure rather
# than a burned LLM run, and the literal is never exported either way.
JOB_ENV_JSON=$(printf '%s' "$JOB_ENV_JSON" | resolve_pulse_env_json) \
    || _die "secret-reference resolution failed for $JOB_ID (store: ~/.nos/secrets.yml — nothing was exported)"
JOB_PAUSED=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].paused')

[[ -x "$JOB_CMD" ]] || _die "registered command is not executable: $JOB_CMD"
echo "✓ pulse_jobs row found: $JOB_ID (paused=$JOB_PAUSED — manual invocation overrides)"

AK_URL=$(echo "$JOB_ENV_JSON" | jq -r '.NOS_AUTHENTIK_URL // ""')
if [[ -n "$AK_URL" ]]; then
    AK_HEALTH=$(curl -sS -k -o /dev/null -w "%{http_code}" "$AK_URL/-/health/live/" 2>/dev/null || echo "000")
    [[ "$AK_HEALTH" == "200" || "$AK_HEALTH" == "204" ]] \
        || _die "Authentik $AK_URL liveness returned $AK_HEALTH"
    echo "✓ Authentik $AK_URL liveness → $AK_HEALTH"
fi

# The walk reads the CHECKOUT, so say which one — an agent anchored at the
# wrong root is the failure this ceremony has already had twice.
echo "✓ Repo root: $REPO_ROOT"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would invoke:"
    echo "  command: $JOB_CMD"
    echo "  args:    $JOB_ARGS_JSON"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

PRE_EVENTS=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'surveyor';")
echo
echo "── Firing surveyor (pre: $PRE_EVENTS surveyor events) ──"
echo

ENV_FILE=$(mktemp /tmp/surveyor-env-XXXXX)
OUTPUT_FILE=$(mktemp /tmp/surveyor-output-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do
        JOB_ARGS_ARR+=("$line")
    done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="surveyor-manual-$(date +%s)"

RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo "── Survey exit: $RUN_EXIT ──"
echo

POST_EVENTS=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'surveyor';")
echo "surveyor events: $PRE_EVENTS → $POST_EVENTS"

# The report is the deliverable. Keep the transcript regardless of exit code:
# a survey that died halfway is still evidence about where it died.
mkdir -p "$(dirname "$REPORT_FILE")"
cp "$OUTPUT_FILE" "$REPORT_FILE"
rm -f "$OUTPUT_FILE"
echo "report: $REPORT_FILE"

if [[ "$RUN_EXIT" != "0" ]]; then
    echo "ERROR: the agent exited $RUN_EXIT — read the report above" >&2
    exit 2
fi
exit 0
