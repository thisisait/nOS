#!/usr/bin/env bash
# =============================================================================
# run-phase5-ceremony.sh — operator-driven conductor self-test (Anatomy A8/A9)
#
# Fires the conductor `self-test-001` Pulse job on demand, off-schedule.
# Pre-flight: probes Bone + Wing + Authentik. Reads the resolved env_json
# from wing.db.pulse_jobs (which Ansible already rendered with the operator's
# global_password_prefix + tenant_domain), so the wrapper doesn't need to
# know the prefix. Post-flight: queries wing.db for the events the run
# emitted + notification (if any), prints a markdown report.
#
# Usage:
#   bash tools/run-phase5-ceremony.sh           # runs the ceremony
#   bash tools/run-phase5-ceremony.sh --dry-run # pre-flight only, no exec
#
# Exit codes:
#   0 — ceremony exit 0, all post-flight checks green
#   1 — ceremony exit ≠ 0 (operator review needed)
#   2 — pre-flight failed (missing dep / unreachable service / no job row)
# =============================================================================

set -uo pipefail

# ── Paths + config ────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:self-test-001"     # SQL LIKE for the conductor pulse_job
DRY_RUN=0
REPORT_FILE="${PHASE5_REPORT_FILE:-${HOME}/.nos/phase5-report-$(date +%Y%m%dT%H%M%S).md}"

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

# ── Pre-flight probes ─────────────────────────────────────────────────────────

_die() { echo "ERROR: $*" >&2; exit 2; }

# THE secret-reference resolver (shared with the Pulse daemon — one
# implementation, N callers; see tools/lib/pulse-env.sh).
# shellcheck source=tools/lib/pulse-env.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/pulse-env.sh"

echo "── Phase 5 ceremony — operator-driven conductor self-test ─────────────────"
echo "WING_DB: $WING_DB"
echo "Report:  $REPORT_FILE"
echo

# Deps
for cmd in sqlite3 curl jq python3; do
    command -v "$cmd" >/dev/null || _die "missing required command: $cmd"
done

# DB
[[ -f "$WING_DB" ]] || _die "Wing DB not found at $WING_DB (pazny.wing/init-db.php hasn't run)"

# Bone liveness — defaults to canonical port 8099. Wing is on a separate
# port (9000); /api/health is a Bone-only route. The pulse_jobs query below
# confirms Wing's DB layer is up by reading wing.db directly.
BONE_URL="${BONE_API_URL:-http://127.0.0.1:8099}"
BONE_HEALTH=$(curl -sS -o /dev/null -w "%{http_code}" "$BONE_URL/api/health" 2>/dev/null || echo "000")
[[ "$BONE_HEALTH" == "200" ]] || _die "Bone $BONE_URL/api/health returned $BONE_HEALTH (Bone daemon down? set BONE_API_URL env var if port differs)"
echo "✓ Bone $BONE_URL/api/health → 200"

PULSE_JOB_ROW=$(sqlite3 -json "$WING_DB" \
    "SELECT id, command, args_json, env_json, paused FROM pulse_jobs WHERE id LIKE '$JOB_ID_PATTERN' LIMIT 1;" 2>/dev/null || true)
if [[ -z "$PULSE_JOB_ROW" || "$PULSE_JOB_ROW" == "[]" ]]; then
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — has the conductor plugin loader hook run? Check tasks/stacks/core-up.yml + plugin loader's pulse-job registration."
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
echo "✓ pulse_jobs row found: $JOB_ID (cmd=$JOB_CMD, paused=$JOB_PAUSED)"

if [[ "$JOB_PAUSED" == "1" ]]; then
    echo "WARN: job is paused — running anyway since this is an ad-hoc invocation" >&2
fi

# Authentik probe via env var from the job
# Token-grant pre-flight (shared: tools/lib/pulse-env.sh). Liveness alone was
# this pre-flight's signature defect — the server answered 200 while THIS
# client's credential died on invalid_grant moments later. Now the check IS
# a client_credentials grant for the job's own client, and it fails closed.
pulse_token_preflight "$JOB_ENV_JSON" \
    || _die "Authentik token-grant pre-flight failed (see message above)"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would have invoked:"
    echo "  command: $JOB_CMD"
    echo "  args:    $JOB_ARGS_JSON"
    echo "  env:     (redacted; \$(echo \$JOB_ENV_JSON | jq 'keys') = $(echo "$JOB_ENV_JSON" | jq -c 'keys'))"
    exit 0
fi

# ── Snapshot pre-run state for diff ───────────────────────────────────────────

PRE_RUN_EVENT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'conductor';")
PRE_RUN_NOTIF_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM notifications WHERE origin_agent = 'conductor';")
RUN_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo
echo "── Firing ceremony (pre: $PRE_RUN_EVENT_COUNT conductor events, $PRE_RUN_NOTIF_COUNT conductor notifications) ──"
echo

# ── Build env + invoke ────────────────────────────────────────────────────────

# Walk env_json keys into export statements. eval-free: jq emits NUL-delimited
# (key, value) pairs and read sets them safely.
ENV_FILE=$(mktemp /tmp/phase5-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

# Resolve args. pulse_jobs.args_json may be empty array.
JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do
        JOB_ARGS_ARR+=("$line")
    done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

# Override PULSE_RUN_ID so the run is distinguishable from scheduled invocations.
export PULSE_RUN_ID="phase5-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/phase5-output-XXXXX)
RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    # ${arr[@]+...} handles the empty-array-under-set-u case (bash doesn't
    # expand it to a literal when the array has zero elements).
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo
echo "── Ceremony exit: $RUN_EXIT ──"
echo

# ── Post-flight verification ──────────────────────────────────────────────────

POST_RUN_EVENT_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM events WHERE source = 'conductor';")
POST_RUN_NOTIF_COUNT=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM notifications WHERE origin_agent = 'conductor';")
EVENT_DELTA=$((POST_RUN_EVENT_COUNT - PRE_RUN_EVENT_COUNT))
NOTIF_DELTA=$((POST_RUN_NOTIF_COUNT - PRE_RUN_NOTIF_COUNT))

# Pull the latest run row from events (start + end share actor_action_id).
LATEST_ACTION_ID=$(sqlite3 -json "$WING_DB" \
    "SELECT actor_action_id FROM events WHERE source = 'conductor' AND ts >= '$RUN_START_ISO' ORDER BY id ASC LIMIT 1;" \
    | jq -r '.[0].actor_action_id // ""')

RUN_EVENTS_JSON=""
if [[ -n "$LATEST_ACTION_ID" ]]; then
    RUN_EVENTS_JSON=$(sqlite3 -json "$WING_DB" \
        "SELECT type, ts, json_extract(result_json, '\$.exit_code') AS exit_code, json_extract(result_json, '\$.summary') AS summary FROM events WHERE actor_action_id = '$LATEST_ACTION_ID' ORDER BY id ASC;")
fi

# ── Markdown report ──────────────────────────────────────────────────────────

{
    echo "# Phase 5 ceremony report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**ceremony exit:** \`$RUN_EXIT\`"
    echo "**actor_action_id:** \`${LATEST_ACTION_ID:-not-found}\`"
    echo
    echo "## Pre-flight"
    echo "- Bone /api/health → 200 ✓"
    echo "- pulse_jobs row → \`$JOB_ID\` ✓"
    [[ -n "$AK_URL" ]] && echo "- Authentik $AK_URL → reachable ✓"
    echo
    echo "## Post-flight"
    echo "- conductor events written: $EVENT_DELTA (was $PRE_RUN_EVENT_COUNT → now $POST_RUN_EVENT_COUNT)"
    echo "- conductor notifications written: $NOTIF_DELTA (was $PRE_RUN_NOTIF_COUNT → now $POST_RUN_NOTIF_COUNT)"
    echo
    if [[ -n "$RUN_EVENTS_JSON" && "$RUN_EVENTS_JSON" != "[]" ]]; then
        echo "## Event lineage (actor_action_id = \`$LATEST_ACTION_ID\`)"
        echo
        echo "| Type | Timestamp | Exit | Summary |"
        echo "|---|---|---|---|"
        echo "$RUN_EVENTS_JSON" | jq -r '.[] | "| \(.type) | \(.ts) | \(.exit_code // "—") | \((.summary // "—") | gsub("[\r\n]"; " ")) |"'
        echo
    fi
    echo "## Ceremony stdout/stderr"
    echo
    echo '```'
    tail -60 "$OUTPUT_FILE"
    echo '```'
    echo
    if [[ "$RUN_EXIT" -eq 0 && "$EVENT_DELTA" -ge 2 ]]; then
        echo "## Verdict"
        echo
        echo "**GREEN** — ceremony exited 0 and emitted ≥2 events with shared actor_action_id."
        echo "Phase 5 pre-req for first non-operator wing.db write is satisfied."
    else
        echo "## Verdict"
        echo
        echo "**RED** — ceremony exit=\`$RUN_EXIT\`, event_delta=$EVENT_DELTA. Triage:"
        echo "1. Read \`Ceremony stdout/stderr\` above for the failing step."
        echo "2. Inspect notifications: \`sqlite3 $WING_DB \"SELECT severity, title FROM notifications WHERE origin_agent = 'conductor' ORDER BY id DESC LIMIT 5;\"\`"
        echo "3. Inspect events: \`sqlite3 $WING_DB \"SELECT type, ts, result_json FROM events WHERE source = 'conductor' ORDER BY id DESC LIMIT 10;\"\`"
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"

echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
