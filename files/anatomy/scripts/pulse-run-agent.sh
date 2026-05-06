#!/usr/bin/env bash
# =============================================================================
# pulse-run-agent.sh — conductor agent runner (Anatomy A8.a, 2026-05-07)
#
# Called by Pulse as a subprocess job. Flow:
#   1. Authenticate to Authentik (client_credentials) → conductor identity.
#   2. POST Wing agent_run_start event (HMAC-signed, source=conductor).
#   3. Run `claude` with the conductor profile + Wing API env vars.
#   4. POST Wing agent_run_end event with exit status.
#
# Env vars (injected via Pulse job env_json — see conductor plugin.yml):
#   NOS_AUTHENTIK_URL              — e.g. https://auth.dev.local
#   NOS_CONDUCTOR_CLIENT_ID        — nos-conductor (default)
#   NOS_CONDUCTOR_CLIENT_SECRET    — {{ global_password_prefix }}_pw_agent_conductor
#   NOS_CONDUCTOR_PROFILE          — Path to conductor.yml agent profile
#   NOS_CONDUCTOR_TASK             — Task prompt for this run (required)
#   WING_API_URL                   — http://127.0.0.1:9000 (default)
#   WING_API_TOKEN                 — {{ conductor_wing_api_token }}
#   WING_EVENTS_HMAC_SECRET        — {{ bone_secret }} (= wing_events_hmac_secret)
#   PULSE_RUN_ID                   — Set by Pulse daemon
#
# Exit codes:
#   0 — conductor completed successfully
#   1 — conductor reported failure or partial result
#   2 — environment/auth/Wing error (check stderr)
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

AUTHENTIK_URL="${NOS_AUTHENTIK_URL:-}"
CLIENT_ID="${NOS_CONDUCTOR_CLIENT_ID:-nos-conductor}"
CLIENT_SECRET="${NOS_CONDUCTOR_CLIENT_SECRET:-}"
CONDUCTOR_PROFILE="${NOS_CONDUCTOR_PROFILE:-}"
TASK_PROMPT="${NOS_CONDUCTOR_TASK:-}"

WING_API_URL="${WING_API_URL:-http://127.0.0.1:9000}"
WING_API_TOKEN="${WING_API_TOKEN:-}"
WING_EVENTS_HMAC_SECRET="${WING_EVENTS_HMAC_SECRET:-}"

RUN_ID="conductor-${PULSE_RUN_ID:-manual-$(date +%s)}"

# A10 actor audit (2026-05-08): actor_id = the Authentik client_id we
# authenticate as; actor_action_id = a UUID that groups all events of
# THIS pulse run (start + end + anything Claude itself emits via Wing
# events API). UUID via Python (always available on macOS) — falls back
# to RUN_ID-derived hex if python3 missing.
ACTOR_ID="${CLIENT_ID}"
if command -v python3 &>/dev/null; then
    ACTOR_ACTION_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
else
    # RFC4122 v4 shape, deterministic-looking — sufficient for grouping.
    ACTOR_ACTION_ID=$(printf '%s' "$RUN_ID-$(date +%s%N)" | shasum -a 256 \
        | awk '{print substr($1,1,8)"-"substr($1,9,4)"-"substr($1,13,4)"-"substr($1,17,4)"-"substr($1,21,12)}')
fi

# ── Validation ────────────────────────────────────────────────────────────────

_die() { echo "ERROR: $*" >&2; exit 2; }

[[ -z "$AUTHENTIK_URL" ]]        && _die "NOS_AUTHENTIK_URL is not set"
[[ -z "$CLIENT_SECRET" ]]        && _die "NOS_CONDUCTOR_CLIENT_SECRET is not set"
[[ -z "$WING_API_TOKEN" ]]       && _die "WING_API_TOKEN is not set"
[[ -z "$WING_EVENTS_HMAC_SECRET" ]] && _die "WING_EVENTS_HMAC_SECRET is not set"
[[ -z "$TASK_PROMPT" ]]          && _die "NOS_CONDUCTOR_TASK is not set"

if ! command -v claude &>/dev/null; then
    _die "claude CLI not found in PATH"
fi
if ! command -v curl &>/dev/null; then
    _die "curl not found in PATH"
fi
if ! command -v openssl &>/dev/null; then
    _die "openssl not found in PATH"
fi

# ── HMAC helper ───────────────────────────────────────────────────────────────

# POST a Wing event with HMAC auth. Args: <json_body>
_post_wing_event() {
    local body="$1"
    local ts
    ts=$(date +%s)
    local sig
    sig=$(printf '%s.%s' "$ts" "$body" \
          | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" \
          | awk '{print $2}')

    local resp
    resp=$(curl -sS -w "\n%{http_code}" \
        -X POST \
        -H "X-Wing-Timestamp: $ts" \
        -H "X-Wing-Signature: $sig" \
        -H "Content-Type: application/json" \
        -d "$body" \
        "$WING_API_URL/api/v1/events" 2>&1) || true

    local code
    code=$(echo "$resp" | tail -n 1)
    if [[ "$code" != "201" ]]; then
        echo "WARN: Wing event POST returned HTTP $code" >&2
    fi
}

# ── Authentik client_credentials ─────────────────────────────────────────────

TOKEN_URL="${AUTHENTIK_URL%/}/application/o/token/"
echo "INFO: obtaining Authentik token for $CLIENT_ID"

TOKEN_RESP=$(curl -sS -w "\n%{http_code}" \
    -X POST \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=client_credentials" \
    --data-urlencode "client_id=${CLIENT_ID}" \
    --data-urlencode "client_secret=${CLIENT_SECRET}" \
    "${TOKEN_URL}" 2>&1) || _die "curl to Authentik failed"

TOKEN_BODY=$(echo "$TOKEN_RESP" | head -n -1)
TOKEN_CODE=$(echo "$TOKEN_RESP" | tail -n 1)

if [[ "$TOKEN_CODE" != "200" ]]; then
    echo "ERROR: Authentik token endpoint returned HTTP $TOKEN_CODE: $TOKEN_BODY" >&2
    exit 2
fi

AUTHENTIK_TOKEN=$(echo "$TOKEN_BODY" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
if [[ -z "$AUTHENTIK_TOKEN" ]]; then
    _die "Authentik returned no access_token"
fi
echo "INFO: Authentik token acquired for $CLIENT_ID"

# ── Wing: agent_run_start ─────────────────────────────────────────────────────

TS_NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
_post_wing_event "$(printf '{"ts":"%s","type":"agent_run_start","run_id":"%s","source":"conductor","actor_id":"%s","actor_action_id":"%s","acted_at":"%s","task":"%s"}' \
    "$TS_NOW" "$RUN_ID" "$ACTOR_ID" "$ACTOR_ACTION_ID" "$TS_NOW" \
    "$(echo "$TASK_PROMPT" | head -c 120 | tr '"\\' "  ")")"

echo "INFO: starting conductor (run_id=$RUN_ID)"

# ── Run claude ────────────────────────────────────────────────────────────────

CLAUDE_EXIT=0
CLAUDE_OUTPUT=""

# Build system prompt from profile if provided.
SYSTEM_PROMPT=""
if [[ -n "$CONDUCTOR_PROFILE" && -f "$CONDUCTOR_PROFILE" ]]; then
    # Extract system_prompt field from YAML (simple grep; no yq dependency).
    SYSTEM_PROMPT=$(grep -A 9999 '^system_prompt:' "$CONDUCTOR_PROFILE" \
        | tail -n +2 \
        | sed 's/^  //' \
        | sed '/^[a-z_]*:/q' \
        | head -n -1)
fi

CLAUDE_ARGS=(--print)
[[ -n "$SYSTEM_PROMPT" ]] && CLAUDE_ARGS+=(--system "$SYSTEM_PROMPT")

CLAUDE_OUTPUT=$(
    WING_API_URL="$WING_API_URL" \
    WING_API_TOKEN="$WING_API_TOKEN" \
    NOS_AUTHENTIK_TOKEN="$AUTHENTIK_TOKEN" \
    NOS_RUN_ID="$RUN_ID" \
    claude "${CLAUDE_ARGS[@]}" "$TASK_PROMPT" 2>&1
) || CLAUDE_EXIT=$?

echo "INFO: claude exited with code $CLAUDE_EXIT"
if [[ -n "$CLAUDE_OUTPUT" ]]; then
    echo "$CLAUDE_OUTPUT" | tail -20
fi

# ── Wing: agent_run_end ───────────────────────────────────────────────────────

TS_END=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RESULT_SUMMARY=$(echo "${CLAUDE_OUTPUT:-}" | tail -3 | head -c 200 | tr '"\\' "  ")
# Same actor_action_id as start → events join in pulse_runs.actor_action_id.
_post_wing_event "$(printf '{"ts":"%s","type":"agent_run_end","run_id":"%s","source":"conductor","actor_id":"%s","actor_action_id":"%s","acted_at":"%s","result":{"exit_code":%d,"summary":"%s"}}' \
    "$TS_END" "$RUN_ID" "$ACTOR_ID" "$ACTOR_ACTION_ID" "$TS_END" \
    "$CLAUDE_EXIT" "$RESULT_SUMMARY")"

echo "INFO: conductor finished (exit=$CLAUDE_EXIT)"
exit "$CLAUDE_EXIT"
