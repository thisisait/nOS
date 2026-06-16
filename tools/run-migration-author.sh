#!/usr/bin/env bash
# =============================================================================
# run-migration-author.sh — operator-driven migration authoring (B4a, 2026-06-16;
#   AgentKit-native default Q8/A2, 2026-06-16)
#
# Fires the migration-author agent on demand for ONE service + recipe. The
# migration-author reads the named MERGED recipe + the operator's plan-choice,
# WRITES the real migration record under files/anatomy/migrations/ + bumps
# <service>_version in default.config.yml (via the gated migration-file-write
# tool), then the trigger layer opens a LOCAL forge MR (tools/migration-pr.sh)
# for the operator to review + merge (GATE 2). It writes+MRs — never merges,
# never provisions, never GitHub.
#
# RUNTIME (Q8/A2) — two paths, AgentKit-native is the DEFAULT:
#   * agentkit (default): runs `php <wing>/bin/run-agent.php
#     --agent=migration-author --trigger=operator` so the run lands in
#     agent_sessions/threads/iterations + OTel spans → Wing /agents + Grafana
#     22-ai-agents + Tempo. This is the unified operational-agent runtime.
#   * cli (fallback): the legacy pulse_jobs `promote-migration` row → the
#     claude-CLI via files/anatomy/scripts/pulse-run-agent.sh. Retained for
#     operator/CI use where the deployed Wing PHP runtime is absent.
#   Select with --cli / --agentkit, or NOS_MIGRATION_AUTHOR_RUNTIME=cli|agentkit
#   (flag wins). Both paths share the same pulse_jobs.env_json (bearer, HMAC,
#   NOS_REPO_ROOT) + the per-run NOS_MIGRATION_SERVICE / NOS_MIGRATION_RECIPE_ID.
#
# Same pre-flight as tools/run-upgrade-architect.sh (Bone health + pulse_jobs
# row + Authentik liveness), post-flight verifier, markdown report to
# ~/.nos/migration-author-report-<ts>.md.
#
# The migration-author's Pulse row is paused=1 by default; this runs it
# off-schedule for the named (service, recipe).
#
# Usage:
#   bash tools/run-migration-author.sh <service> <recipe_id>             # author (AgentKit)
#   bash tools/run-migration-author.sh <service> <recipe_id> --cli       # CLI fallback
#   bash tools/run-migration-author.sh <service> <recipe_id> --dry-run   # preflight
#
# Exit codes:
#   0 — agent exit 0 (nothing to author — no merged recipe gap / already migrated)
#   1 — agent exit 1 (authored a migration record + opened the MR; needs review)
#   2 — pre-flight failed / bad args
# =============================================================================

set -uo pipefail

WING_DB="${WING_DB_PATH:-${HOME}/wing/app/data/wing.db}"
WING_APP_DIR="${WING_APP_DIR:-${HOME}/wing/app}"
JOB_ID_PATTERN="%:promote-migration"
# Default to the AgentKit-native runtime (Q8/A2); --cli (or
# NOS_MIGRATION_AUTHOR_RUNTIME=cli) selects the legacy pulse-CLI fallback.
RUNTIME="${NOS_MIGRATION_AUTHOR_RUNTIME:-agentkit}"
DRY_RUN=0
SERVICE=""
RECIPE_ID=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --cli) RUNTIME=cli ;;
        --agentkit) RUNTIME=agentkit ;;
        -h|--help) sed -n '2,40p' "$0" | sed 's/^# \?//'; exit 0 ;;
        -*) echo "ERROR: unknown flag '$arg' (use --cli, --agentkit, --dry-run or --help)" >&2; exit 2 ;;
        *)
            if [[ -z "$SERVICE" ]]; then SERVICE="$arg"
            elif [[ -z "$RECIPE_ID" ]]; then RECIPE_ID="$arg"
            else echo "ERROR: unexpected positional '$arg'" >&2; exit 2; fi
            ;;
    esac
done

case "$RUNTIME" in
    agentkit|cli) ;;
    *) echo "ERROR: NOS_MIGRATION_AUTHOR_RUNTIME must be 'agentkit' or 'cli' (got '$RUNTIME')" >&2; exit 2 ;;
esac

if [[ -z "$SERVICE" || -z "$RECIPE_ID" ]]; then
    echo "usage: bash tools/run-migration-author.sh <service> <recipe_id> [--dry-run]" >&2
    exit 2
fi

REPORT_FILE="${MIGRATION_AUTHOR_REPORT_FILE:-${HOME}/.nos/migration-author-report-$(date +%Y%m%dT%H%M%S).md}"

_die() { echo "ERROR: $*" >&2; exit 2; }

echo "── nOS migration-author — operator-driven migration authoring ──────────"
echo "Service: $SERVICE"
echo "Recipe:  $RECIPE_ID"
echo "Runtime: $RUNTIME$([[ "$RUNTIME" == agentkit ]] && echo ' (native — sessions/OTel → /agents + Grafana 22-ai-agents)' || echo ' (CLI fallback)')"
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
    _die "no pulse_jobs row matches '$JOB_ID_PATTERN' — has the migration-author agent registration run? Re-run the playbook after the profile lands in Wing."
fi
JOB_ID=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].id')
JOB_CMD=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].command')
JOB_ARGS_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].args_json')
JOB_ENV_JSON=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].env_json')
JOB_PAUSED=$(echo "$PULSE_JOB_ROW" | jq -r '.[0].paused')

[[ -x "$JOB_CMD" ]] || _die "registered command is not executable: $JOB_CMD"
echo "✓ pulse_jobs row found: $JOB_ID (paused=$JOB_PAUSED — manual invocation overrides)"

# AgentKit-native runtime needs the deployed Wing run-agent.php + a php runtime.
# (The pulse_jobs.env_json above still supplies the shared bearer/HMAC/NOS_REPO_ROOT
# for the native path — Runner reads the same Wing API env.)
RUN_AGENT_BIN="${WING_APP_DIR}/bin/run-agent.php"
if [[ "$RUNTIME" == agentkit ]]; then
    command -v php >/dev/null || _die "php not found — AgentKit-native migration-author needs the Wing PHP runtime (use --cli for the claude-CLI fallback)"
    [[ -f "$RUN_AGENT_BIN" ]] || _die "Wing run-agent.php not found at $RUN_AGENT_BIN — deploy Wing, set WING_APP_DIR, or use --cli for the fallback"
    echo "✓ AgentKit runner: $RUN_AGENT_BIN"
fi

AK_URL=$(echo "$JOB_ENV_JSON" | jq -r '.NOS_AUTHENTIK_URL // ""')
if [[ -n "$AK_URL" ]]; then
    AK_HEALTH=$(curl -sS -k -o /dev/null -w "%{http_code}" "$AK_URL/-/health/live/" 2>/dev/null || echo "000")
    [[ "$AK_HEALTH" == "200" || "$AK_HEALTH" == "204" ]] || _die "Authentik $AK_URL liveness returned $AK_HEALTH"
    echo "✓ Authentik $AK_URL liveness → $AK_HEALTH"
fi

DRAFTS_BEFORE=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM migrations_authored WHERE review_status='draft';" 2>/dev/null || echo "?")
echo "✓ Migrations currently in draft: $DRAFTS_BEFORE"

if [[ "$DRY_RUN" == "1" ]]; then
    echo
    echo "DRY RUN — pre-flight green. Would invoke ($RUNTIME):"
    if [[ "$RUNTIME" == agentkit ]]; then
        echo "  command: php $RUN_AGENT_BIN --agent=migration-author --trigger=operator"
        echo "           (native AgentKit Runner — writes agent_sessions/threads/iterations + OTel)"
    else
        echo "  command: $JOB_CMD"
        echo "  args:    $JOB_ARGS_JSON"
    fi
    echo "  service: $SERVICE   recipe: $RECIPE_ID"
    echo "  env keys: $(echo "$JOB_ENV_JSON" | jq -c 'keys')"
    exit 0
fi

# SQLite stores created_at as 'YYYY-MM-DD HH:MM:SS' (UTC, no T/Z); compare in
# that exact shape or the >= window silently matches nothing (space < 'T').
RUN_START_SQLITE=$(date -u +"%Y-%m-%d %H:%M:%S")
echo
echo "── Firing migration-author for ${SERVICE}/${RECIPE_ID} (drafts before: $DRAFTS_BEFORE) ──"
echo

# The per-run service + recipe are injected as env (NOS_MIGRATION_SERVICE /
# NOS_MIGRATION_RECIPE_ID); the agent's system prompt reads them. We merge them
# into the pulse_jobs.env_json so they sit alongside the agent's bearer token.
ENV_FILE=$(mktemp /tmp/migration-author-env-XXXXX)
trap 'rm -f "$ENV_FILE"' EXIT
echo "$JOB_ENV_JSON" | jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' > "$ENV_FILE"
{
    printf 'export NOS_MIGRATION_SERVICE=%q\n' "$SERVICE"
    printf 'export NOS_MIGRATION_RECIPE_ID=%q\n' "$RECIPE_ID"
} >> "$ENV_FILE"

JOB_ARGS_ARR=()
if [[ "$JOB_ARGS_JSON" != "[]" && "$JOB_ARGS_JSON" != "null" ]]; then
    while IFS= read -r line; do JOB_ARGS_ARR+=("$line"); done < <(echo "$JOB_ARGS_JSON" | jq -r '.[]')
fi

export PULSE_RUN_ID="migration-author-manual-$(date +%s)"

OUTPUT_FILE=$(mktemp /tmp/migration-author-output-XXXXX)
RUN_EXIT=0
if [[ "$RUNTIME" == agentkit ]]; then
    # AgentKit-native: Runner::run writes agent_sessions/threads/iterations +
    # batches OTel spans (agent.session → thread → llm.call → tool.use) to Alloy
    # :4318 → Tempo, so the run shows in Wing /agents + Grafana 22-ai-agents.
    # The gated migration-file-write tool is the only write surface; the MR-open
    # is the A3 trigger-layer post-step, NOT this script. --trigger=operator.
    (
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        php "$RUN_AGENT_BIN" --agent=migration-author --trigger=operator
    ) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?
else
    # CLI fallback: the claude-CLI via pulse-run-agent.sh (the registered
    # pulse_jobs command). No agent_sessions row, no OTel — operator/CI use
    # where the deployed Wing PHP runtime is absent.
    (
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        "$JOB_CMD" ${JOB_ARGS_ARR[@]+"${JOB_ARGS_ARR[@]}"}
    ) > "$OUTPUT_FILE" 2>&1 || RUN_EXIT=$?
fi

echo
echo "── Migration-author exit: $RUN_EXIT ──"
echo

DRAFTS_AFTER=$(sqlite3 "$WING_DB" "SELECT COUNT(*) FROM migrations_authored WHERE review_status='draft';" 2>/dev/null || echo "?")
NEWLY_DRAFTED=$(sqlite3 -json "$WING_DB" \
    "SELECT service, migration_id, plan_mode, mr_url FROM migrations_authored WHERE review_status='draft' AND created_at >= '$RUN_START_SQLITE';" 2>/dev/null || echo "[]")

# AgentKit-native: run-agent.php prints a JSON summary with the session_uuid on
# stdout (deep-linkable at /agents/migration-author/sessions/<uuid>). Lift it for
# the report. Empty under the CLI fallback (no AgentKit session).
SESSION_UUID=""
if [[ "$RUNTIME" == agentkit ]]; then
    SESSION_UUID=$(grep -o '"session_uuid"[^,}]*' "$OUTPUT_FILE" 2>/dev/null \
        | head -1 | sed 's/.*"session_uuid"[^"]*"\([^"]*\)".*/\1/' || true)
fi

# Did THIS run produce an authored migration? Authoritative signal independent of
# the process exit code — the two runtimes carry OPPOSITE exit-1 meanings (CLI:
# authored+review sentinel; AgentKit: Runner error), so we key the verdict on the
# draft delta the A3 MR-open post-step records, not on $RUN_EXIT alone.
AUTHORED_THIS_RUN=0
[[ -n "$NEWLY_DRAFTED" && "$NEWLY_DRAFTED" != "[]" ]] && AUTHORED_THIS_RUN=1

{
    echo "# nOS migration-author report — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
    echo "**run_id:** \`$PULSE_RUN_ID\`"
    echo "**runtime:** \`$RUNTIME\`"
    [[ -n "$SESSION_UUID" ]] && echo "**session:** \`$SESSION_UUID\` → /agents/migration-author/sessions/$SESSION_UUID"
    echo "**service / recipe:** \`$SERVICE\` / \`$RECIPE_ID\`"
    echo "**migration-author exit:** \`$RUN_EXIT\`"
    echo "**migrations drafted:** $DRAFTS_BEFORE → $DRAFTS_AFTER"
    echo
    echo "## Migrations authored this run"
    echo
    if [[ -n "$NEWLY_DRAFTED" && "$NEWLY_DRAFTED" != "[]" ]]; then
        echo "$NEWLY_DRAFTED" | jq -r '.[] | "- **\(.service)** \(.migration_id // "?") [\(.plan_mode // "migration")] — MR: \(.mr_url // "(forge unavailable — see report below)")"'
    else
        echo "_None — nothing needed authoring (no merged recipe gap, or installed already matches the target). See the agent report below._"
    fi
    echo
    echo "## Migration-author stdout/stderr"
    echo
    echo '```'
    tail -60 "$OUTPUT_FILE"
    echo '```'
    echo
    echo "## Verdict"
    echo
    if [[ "$RUNTIME" == agentkit ]]; then
        # AgentKit exit-code semantics: 0=clean session, 1=Runner error,
        # 2=config error. The sentinel (NOS_AGENT_EXIT) is NOT lifted into the
        # process exit on this runtime (known two-runtime gap), so the draft
        # delta is the authoritative "authored?" signal.
        if [[ "$RUN_EXIT" -ge 1 ]]; then
            echo "**RED** — AgentKit Runner exited \`$RUN_EXIT\` (1=terminated/error, 2=config error). The session is in /agents${SESSION_UUID:+/migration-author/sessions/$SESSION_UUID}; read the stdout/stderr above."
        elif [[ "$AUTHORED_THIS_RUN" -eq 1 ]]; then
            echo "**REVIEW** — migration-author authored a migration record + version bump (the A3 MR-open post-step opens the LOCAL forge MR). Review the MR on the forge (GATE 2), merge it, then provision any coexistence track with \`ansible-playbook main.yml --tags coexistence\` (dry-run first with \`-e coexist_dry_run=true\`)."
        else
            echo "**GREEN** — clean AgentKit session, nothing to author for \`$SERVICE/$RECIPE_ID\` (no merged recipe gap / already migrated). Session lineage in /agents + Grafana 22-ai-agents."
        fi
    else
        # CLI fallback — pulse-run-agent.sh lifts the NOS_AGENT_EXIT sentinel:
        # 0=nothing to author, 1=authored+review, 2=env/forge/auth error.
        if [[ "$RUN_EXIT" -eq 0 ]]; then
            echo "**GREEN** — migration-author exit 0. Nothing to author for \`$SERVICE/$RECIPE_ID\` (no merged recipe gap / already migrated)."
        elif [[ "$RUN_EXIT" -eq 1 ]]; then
            echo "**REVIEW** — migration-author authored a migration record + version bump and opened a LOCAL forge MR. Review the MR on the forge (GATE 2), merge it, then provision any coexistence track with \`ansible-playbook main.yml --tags coexistence\` (dry-run first with \`-e coexist_dry_run=true\`)."
        else
            echo "**RED** — migration-author failed at exit \`$RUN_EXIT\` (env/forge/auth/Wing error, or migration-pr.sh exit 2). Read the stdout/stderr above."
        fi
    fi
} | tee "$REPORT_FILE"

rm -f "$OUTPUT_FILE"
echo
echo "── Full report saved to: $REPORT_FILE ──"
exit "$RUN_EXIT"
