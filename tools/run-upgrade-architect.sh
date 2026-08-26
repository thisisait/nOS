#!/usr/bin/env bash
# =============================================================================
# run-upgrade-architect.sh — operator-driven recipe authoring (W5-B5, 2026-05-27)
#
# Fires the upgrade-architect agent's `recipe-author` Pulse job on demand. The
# architect reads the /upgrades version matrix, finds coverage gaps the advisor
# can't act on (no matching recipe / stale recipe / uncovered major), DRAFTS a
# recipe for each in its report, and for breaking gaps QUEUES coexistence prep
# via POST /api/v1/coexistence/<svc>/queue. It proposes only — the operator
# commits each drafted YAML and applies coexistence with
# `ansible-playbook main.yml --tags coexistence`.
#
# The shared launcher shape (see tools/run-surveyor.sh): pre-flight (Bone health
# + pulse_jobs row + Authentik token grant), env from pulse_jobs.env_json,
# post-flight verifier, markdown report to ~/.nos/upgrade-architect-report-<ts>.md.
#
# The architect's Pulse row is paused=1 by default; this runs it off-schedule.
#
# Usage:
#   bash tools/run-upgrade-architect.sh           # run the architect
#   bash tools/run-upgrade-architect.sh --dry-run # pre-flight only
#
# Exit codes:
#   0 — architect exit 0 (full coverage, nothing drafted or queued)
#   1 — architect exit 1 (drafted recipes / queued coexistence need review)
#   2 — pre-flight failed
# =============================================================================

set -uo pipefail

WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
JOB_ID_PATTERN="%:recipe-author"
DRY_RUN=0
REPORT_FILE="${UPGRADE_ARCHITECT_REPORT_FILE:-${HOME}/.nos/upgrade-architect-report-$(date +%Y%m%dT%H%M%S).md}"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "ERROR: unknown arg '$arg' (use --dry-run or --help)" >&2; exit 2 ;;
    esac
done

_die() { echo "ERROR: $*" >&2; exit 2; }

# THE secret-reference resolver (shared with the Pulse daemon — one
# implementation, N callers; see tools/lib/pulse-env.sh).
# shellcheck source=tools/lib/pulse-env.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/pulse-env.sh"

echo "── nOS upgrade-architect — operator-driven recipe authoring ────────────"
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
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — has the upgrade-architect agent registration run? Re-run the playbook after the profile lands in Wing."
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

QUEUED_BEFORE=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM coexistence_planned WHERE status='planned';" 2>/dev/null || echo "?")
echo "✓ Coexistence currently queued: $QUEUED_BEFORE"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would invoke:"
    echo "  command: $JOB_CMD"
    echo "  args:    $JOB_ARGS_JSON"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

# SQLite stores planned_at as 'YYYY-MM-DD HH:MM:SS' (UTC, no T/Z); compare in
# that exact shape or the >= window silently matches nothing (space < 'T').
RUN_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RUN_START_SQLITE=$(date -u +"%Y-%m-%d %H:%M:%S")
echo
echo "── Firing upgrade-architect (coexistence queued before: $QUEUED_BEFORE) ──"
echo

ENV_FILE=$(mktemp /tmp/upgrade-architect-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do JOB_ARGS_ARR+=("$line"); done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="upgrade-architect-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/upgrade-architect-output-XXXXX)
RUN_EXIT=0
(
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?

echo
echo "── Architect exit: $RUN_EXIT ──"
echo

QUEUED_AFTER=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM coexistence_planned WHERE status='planned';" 2>/dev/null || echo "?")
NEWLY_QUEUED=$(sqlite3 -json "$WING_DB" \
    "SELECT service, tag, target_version FROM coexistence_planned WHERE status='planned' AND planned_at >= '$RUN_START_SQLITE';" 2>/dev/null || echo "[]")

{
    echo "# nOS upgrade-architect report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**architect exit:** \`$RUN_EXIT\`"
    echo "**coexistence queued:** $QUEUED_BEFORE → $QUEUED_AFTER"
    echo
    echo "## Coexistence queued this run"
    echo
    if [[ -n "$NEWLY_QUEUED" && "$NEWLY_QUEUED" != "[]" ]]; then
        echo "$NEWLY_QUEUED" | jq -r '.[] | "- **\(.service)** /\(.tag) → \(.target_version // "?")"'
    else
        echo "_None — no breaking coverage gap needed a coexistence track. Drafted recipes (if any) are in the architect report below._"
    fi
    echo
    echo "## Architect stdout/stderr"
    echo
    echo '```'
    tail -60 "$OUTPUT_FILE"
    echo '```'
    echo
    # The drafts do NOT live in the stdout tail above — the architect POSTs its
    # full report (```yaml drafts included) as a conductor_report event, and on
    # 2026-08-25 this file claimed "review the drafted YAML in the report"
    # while holding 45 lines and zero yaml blocks. Pull the real report out of
    # wing.db through the lossless reader (a hand extraction ate a backslash
    # level that run — six of ten drafts failed to parse). --since scopes to
    # THIS run so a stale report cannot masquerade as today's.
    echo "## Architect report (from wing.db conductor_report event)"
    echo
    if ! WING_DB_PATH="$WING_DB" python3 "$(dirname "$0")/agent-report.py" \
            --agent upgrade-architect --since "$RUN_START_ISO" 2>/dev/null; then
        echo "_No conductor_report event landed for this run — the drafts are"
        echo "NOT in this file. Check \`tools/agent-report.py --agent upgrade-architect\`"
        echo "and the stdout tail above._"
    fi
    echo
    echo "## Verdict"
    echo
    if [[ "$RUN_EXIT" -eq 0 ]]; then
        echo "**GREEN** — architect exit 0. Full recipe coverage; nothing drafted or queued."
    elif [[ "$RUN_EXIT" -eq 1 ]]; then
        echo "**REVIEW** — architect drafted recipes and/or queued coexistence. Review the drafted YAML in the \"Architect report\" section above, commit each to \`upgrades/<service>.yml\`, then apply any coexistence with \`ansible-playbook main.yml --tags coexistence\` (dry-run first with \`-e coexist_dry_run=true\`)."
    else
        echo "**RED** — architect failed at exit \`$RUN_EXIT\` (env/auth/Wing error). Read the stdout/stderr above."
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"
echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
