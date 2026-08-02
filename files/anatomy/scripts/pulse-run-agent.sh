#!/usr/bin/env bash
# =============================================================================
# pulse-run-agent.sh — generic agent runner (Anatomy A8.a, 2026-05-07;
#   genericized A9.3 2026-05-17 from conductor-only to NOS_AGENT_*).
#
# Called by Pulse as a subprocess job. Flow:
#   1. Authenticate to Authentik (client_credentials) → agent identity.
#   2. POST Wing agent_run_start event (HMAC-signed, source=<agent_name>).
#   3. Run `claude` with the agent profile + Wing API env vars.
#   4. POST Wing agent_run_end event with exit status.
#   5. On non-zero exit, fire A9 notification (high/critical per exit class).
#
# Env vars (injected via Pulse job env_json — see <agent>.yml). Reads
# NOS_AGENT_* first, falls back to NOS_CONDUCTOR_* for backward compat
# (so the existing conductor Pulse job keeps working unchanged):
#   NOS_AUTHENTIK_URL              — e.g. https://auth.dev.local
#   NOS_AGENT_NAME                 — e.g. conductor / remediator (default: conductor)
#   NOS_AGENT_CLIENT_ID            — Authentik client_id (default: nos-<agent_name>)
#   NOS_AGENT_CLIENT_SECRET        — Authentik client_secret (required)
#   NOS_AGENT_PROFILE              — Path to <agent>.yml profile
#   NOS_AGENT_TASK                 — Task prompt for this run (required)
#   WING_API_URL                   — http://127.0.0.1:9000 (default)
#   WING_API_TOKEN                 — Wing bearer for the agent
#   WING_EVENTS_HMAC_SECRET        — {{ bone_secret }} (= wing_events_hmac_secret)
#   PULSE_RUN_ID                   — Set by Pulse daemon
#
# Exit codes:
#   0 — agent completed successfully
#   1 — agent reported actionable findings (operator review needed)
#   2 — environment/auth/Wing error (check stderr)
# =============================================================================

set -euo pipefail

# ── Config (NOS_AGENT_* with NOS_CONDUCTOR_* fallback) ───────────────────────

AUTHENTIK_URL="${NOS_AUTHENTIK_URL:-}"
AGENT_NAME="${NOS_AGENT_NAME:-conductor}"
CLIENT_ID="${NOS_AGENT_CLIENT_ID:-${NOS_CONDUCTOR_CLIENT_ID:-nos-${AGENT_NAME}}}"
CLIENT_SECRET="${NOS_AGENT_CLIENT_SECRET:-${NOS_CONDUCTOR_CLIENT_SECRET:-}}"
AGENT_PROFILE="${NOS_AGENT_PROFILE:-${NOS_CONDUCTOR_PROFILE:-}}"
TASK_PROMPT="${NOS_AGENT_TASK:-${NOS_CONDUCTOR_TASK:-}}"

WING_API_URL="${WING_API_URL:-http://127.0.0.1:9000}"
WING_API_TOKEN="${WING_API_TOKEN:-}"
WING_EVENTS_HMAC_SECRET="${WING_EVENTS_HMAC_SECRET:-}"

RUN_ID="${AGENT_NAME}-${PULSE_RUN_ID:-manual-$(date +%s)}"

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
[[ -z "$CLIENT_SECRET" ]]        && _die "NOS_AGENT_CLIENT_SECRET (or NOS_CONDUCTOR_CLIENT_SECRET) is not set"
[[ -z "$WING_API_TOKEN" ]]       && _die "WING_API_TOKEN is not set"
[[ -z "$WING_EVENTS_HMAC_SECRET" ]] && _die "WING_EVENTS_HMAC_SECRET is not set"
[[ -z "$TASK_PROMPT" ]]          && _die "NOS_AGENT_TASK (or NOS_CONDUCTOR_TASK) is not set"

if ! command -v claude &>/dev/null; then
    _die "claude CLI not found in PATH"
fi
if ! command -v curl &>/dev/null; then
    _die "curl not found in PATH"
fi
if ! command -v openssl &>/dev/null; then
    _die "openssl not found in PATH"
fi

# ── Sequential run lock (agent-run mutex) ────────────────────────────────────
# claude-CLI agents MUST run one-at-a-time. Firing several concurrently made
# all participants die mid-run — only agent_run_start landed, never
# agent_run_end (2026-05-27; memory agent-two-runtime-session-gap). Until now
# "run them sequentially" was operator discipline, unenforced in code; this
# mutex enforces it at the single chokepoint every agent goes through.
#
# macOS ships no `flock`, so use an atomic `mkdir` lock (POSIX-atomic on all
# FS) with a PID-liveness check to reclaim a lock left by a crashed run. The
# lock is taken AFTER validation (a misconfigured run fails fast without ever
# holding it) and released on ANY exit via the trap — normal finish, _die, or
# claude failure all free it for the next agent. Release uses rmdir + rm -f
# (never `rm -rf`) so a misset NOS_AGENT_LOCK_DIR can't widen the blast radius.
NOS_AGENT_LOCK="${NOS_AGENT_LOCK_DIR:-${HOME}/.nos/agent-run.lock}"
_release_agent_lock() {
    rm -f "$NOS_AGENT_LOCK/owner" 2>/dev/null || true
    rmdir "$NOS_AGENT_LOCK" 2>/dev/null || true
}
mkdir -p "$(dirname "$NOS_AGENT_LOCK")"
if ! mkdir "$NOS_AGENT_LOCK" 2>/dev/null; then
    _lock_owner=$(cat "$NOS_AGENT_LOCK/owner" 2>/dev/null || true)
    _lock_pid="${_lock_owner%% *}"
    if [[ -n "$_lock_pid" ]] && kill -0 "$_lock_pid" 2>/dev/null; then
        echo "ERROR: another nOS agent run holds the lock — ${_lock_owner}." >&2
        echo "       claude-CLI agents must run sequentially (concurrent runs crash mid-run)." >&2
        echo "       Wait for it to finish, or remove ${NOS_AGENT_LOCK} if it is stale." >&2
        exit 2
    fi
    echo "WARN: reclaiming stale agent lock (owner '${_lock_owner:-none}' not alive)" >&2
    _release_agent_lock
    mkdir "$NOS_AGENT_LOCK" 2>/dev/null || _die "could not acquire agent lock at $NOS_AGENT_LOCK"
fi
printf '%s %s %s\n' "$$" "$AGENT_NAME" "$(date -u +%FT%TZ)" > "$NOS_AGENT_LOCK/owner"
trap '_release_agent_lock' EXIT

# ── HMAC helper ───────────────────────────────────────────────────────────────

# POST a Wing event with HMAC auth. Args: <json_body>
#
# IMPORTANT: body MUST be canonical JSON (sorted keys, no whitespace). Bone's
# HMAC verifier re-canonicalizes the parsed dict via Python
# `json.dumps(body, separators=(',',':'), sort_keys=True)` before computing
# the expected HMAC. If the bash-built body has a different key order or
# whitespace shape, signatures never match and Bone returns 401 silently.
# Surfaced live 2026-05-17 — every pulse-run-agent.sh agent_run_start/end
# was 401'ing because the printf'd JSON wasn't key-sorted.
#
# Callers must build the body with `jq -a --sort-keys -c` to guarantee canonical
# form. `-a` is not optional: Bone re-serialises the parsed body with Python
# json.dumps, whose ensure_ascii defaults TRUE, so any non-ASCII byte signed
# raw here is verified as \uXXXX there and the HMAC cannot match. On a
# Czech-operated estate that is every title with diacritics. Sorting alone
# was the 2026-05-17 lesson; encoding is the 2026-07-27 one.
_post_wing_event() {
    local body="$1"
    local ts
    ts=$(date +%s)
    local sig
    sig=$(printf '%s.%s' "$ts" "$body" \
          | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" \
          | awk '{print $NF}')

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

# POST a Bone notification with HMAC auth (Anatomy A9, 2026-05-16). Args:
# <severity> <title> <body_markdown>. Channels resolved by Bone via the
# agent profile's notification: routing block (looked up by origin_agent
# == AGENT_NAME).
_post_wing_notification() {
    local sev="$1" title="$2" body_md="$3"
    local payload ts sig
    payload=$(jq -a --sort-keys -nc \
        --arg sev "$sev" --arg title "$title" --arg body "$body_md" \
        --arg agent "$AGENT_NAME" \
        --arg actor "$ACTOR_ID" --arg action_id "$ACTOR_ACTION_ID" \
        '{severity: $sev, title: $title, body: $body,
          origin_agent: $agent, actor_id: ("agent:" + $actor),
          actor_action_id: $action_id}')
    ts=$(date +%s)
    sig=$(printf '%s.%s' "$ts" "$payload" \
          | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" \
          | awk '{print $NF}')
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "X-Wing-Timestamp: $ts" \
        -H "X-Wing-Signature: $sig" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$WING_API_URL/api/v1/notifications" 2>&1 || echo "000")
    if [[ "$code" != "200" && "$code" != "201" ]]; then
        echo "WARN: notification POST returned HTTP $code" >&2
    fi
}

# ── Authentik client_credentials ─────────────────────────────────────────────
#
# Scope request (2026-05-27): Authentik's client_credentials flow only grants
# scopes that are EXPLICITLY requested (and have a scopemapping). Without a
# `scope` param the issued JWT carries an empty scope claim, so EVERY scoped
# Bone endpoint (/api/state, migrations, upgrades, …) returns 403. Request the
# agent's capability scopes: NOS_AGENT_SCOPES env, else the `capabilities:`
# list in the agent profile.
AGENT_SCOPES="${NOS_AGENT_SCOPES:-}"
if [[ -z "$AGENT_SCOPES" && -n "$AGENT_PROFILE" && -f "$AGENT_PROFILE" ]]; then
    # Extract the bare `capabilities:` list (one scope per `  - ` item) until
    # the next top-level key. Scopes are bare tokens (no quotes), so no gsub.
    AGENT_SCOPES=$(awk '
        /^capabilities:/ {grab=1; next}
        grab && /^[^[:space:]#]/ {exit}
        grab && /^[[:space:]]+-[[:space:]]/ {sub(/^[[:space:]]*-[[:space:]]*/,""); sub(/[[:space:]]*#.*$/,""); printf "%s ", $0}
    ' "$AGENT_PROFILE" | sed 's/[[:space:]]*$//')
fi

TOKEN_URL="${AUTHENTIK_URL%/}/application/o/token/"
echo "INFO: obtaining Authentik token for $CLIENT_ID${AGENT_SCOPES:+ (scopes: $AGENT_SCOPES)}"

_scope_args=()
[[ -n "$AGENT_SCOPES" ]] && _scope_args=(--data-urlencode "scope=${AGENT_SCOPES}")

TOKEN_RESP=$(curl -sS -w "\n%{http_code}" \
    -X POST \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=client_credentials" \
    --data-urlencode "client_id=${CLIENT_ID}" \
    --data-urlencode "client_secret=${CLIENT_SECRET}" \
    ${_scope_args[@]+"${_scope_args[@]}"} \
    "${TOKEN_URL}" 2>&1) || _die "curl to Authentik failed"

TOKEN_BODY=$(echo "$TOKEN_RESP" | sed '$d')   # all lines except the last (portable; macOS BSD head lacks `-n -N`)
TOKEN_CODE=$(echo "$TOKEN_RESP" | tail -n 1)

if [[ "$TOKEN_CODE" != "200" ]]; then
    echo "ERROR: Authentik token endpoint returned HTTP $TOKEN_CODE: $TOKEN_BODY" >&2
    exit 2
fi

# Authentik returns the field with a space after the colon (`"access_token": "..."`)
# whereas a tighter regex without the space would silently miss it. Use python3 (which
# we already require for the UUID) for a robust JSON parse.
AUTHENTIK_TOKEN=$(echo "$TOKEN_BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
if [[ -z "$AUTHENTIK_TOKEN" ]]; then
    _die "Authentik returned no access_token"
fi
echo "INFO: Authentik token acquired for $CLIENT_ID"

# ── Wing: agent_run_start ─────────────────────────────────────────────────────

TS_NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Build canonical (sort_keys + compact) JSON via jq so Bone's HMAC
# verifier matches. Safe-escapes the task prompt too — printf-based
# inline JSON would break on backslashes / quotes / unicode.
TASK_PREVIEW=$(echo "$TASK_PROMPT" | head -c 120 | tr -d '\n')
_post_wing_event "$(jq -a --sort-keys -nc \
    --arg ts "$TS_NOW" \
    --arg run_id "$RUN_ID" \
    --arg src "$AGENT_NAME" \
    --arg actor_id "$ACTOR_ID" \
    --arg action_id "$ACTOR_ACTION_ID" \
    --arg task "$TASK_PREVIEW" \
    '{ts:$ts, type:"agent_run_start", run_id:$run_id, source:$src,
      actor_id:$actor_id, actor_action_id:$action_id, acted_at:$ts,
      task:$task}')"

echo "INFO: starting ${AGENT_NAME} (run_id=$RUN_ID)"

# ── Run claude ────────────────────────────────────────────────────────────────

CLAUDE_EXIT=0
CLAUDE_OUTPUT=""

# Build system prompt from profile if provided.
SYSTEM_PROMPT=""
if [[ -n "$AGENT_PROFILE" && -f "$AGENT_PROFILE" ]]; then
    # Extract system_prompt field from YAML (simple grep; no yq dependency).
    SYSTEM_PROMPT=$(grep -A 9999 '^system_prompt:' "$AGENT_PROFILE" \
        | tail -n +2 \
        | sed 's/^  //' \
        | sed '/^[a-z_]*:/q' \
        | sed '$d')   # drop the trailing 'next-key:' line that ended the slice
fi

# `--output-format json`: yields a single result object with .result (final
# text) + .usage (token tally) + .total_cost_usd, so the agent_run_end event
# can carry real token counts (otherwise the /agents session shows 0/0 for
# every pulse-run agent — the claude-CLI runtime had no usage source).
CLAUDE_ARGS=(--print --output-format json --permission-mode bypassPermissions)
# claude CLI 2.x flag is `--system-prompt` (not `--system`).
# `--permission-mode bypassPermissions`: the runner is a non-interactive
# subprocess; we cannot answer permission prompts. The conductor is
# already gated by Authentik client_credentials + Wing bearer scope —
# permission gating at the inner-claude layer is redundant and blocks
# every Bash/curl call the ceremony needs.
[[ -n "$SYSTEM_PROMPT" ]] && CLAUDE_ARGS+=(--system-prompt "$SYSTEM_PROMPT")
# `NOS_AGENT_MODEL` (pulse_jobs.env_json): pins the model tier per ceremony.
# Without it claude falls back to the operator's default — the most expensive
# tier — which bulk jobs like taxonomy-describe must never inherit.
[[ -n "${NOS_AGENT_MODEL:-}" ]] && CLAUDE_ARGS+=(--model "$NOS_AGENT_MODEL")

# Capture the JSON envelope on stdout; keep stderr separate so a warning
# line can't corrupt the JSON parse.
CLAUDE_ERR=$(mktemp /tmp/pulse-agent-err-XXXXX)
CLAUDE_JSON=$(
    WING_API_URL="$WING_API_URL" \
    WING_API_TOKEN="$WING_API_TOKEN" \
    NOS_AUTHENTIK_TOKEN="$AUTHENTIK_TOKEN" \
    NOS_RUN_ID="$RUN_ID" \
    claude "${CLAUDE_ARGS[@]}" "$TASK_PROMPT" 2>"$CLAUDE_ERR"
) || CLAUDE_EXIT=$?

# Extract .result (human text) + .usage tokens. On any parse failure (claude
# died before emitting JSON, or emitted plain text) fall back to the raw
# stdout and leave token counts empty — the event then carries 0s, not a crash.
TOK_IN=""; TOK_OUT=""; TOK_CACHE=""; COST=""
CLAUDE_OUTPUT=$(printf '%s' "$CLAUDE_JSON" | python3 -c '
import sys, json
try:
    print(json.load(sys.stdin).get("result", ""), end="")
except Exception:
    sys.exit(3)
' 2>/dev/null) || CLAUDE_OUTPUT="$CLAUDE_JSON"
read -r TOK_IN TOK_OUT TOK_CACHE COST < <(printf '%s' "$CLAUDE_JSON" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin); u = d.get("usage") or {}
except Exception:
    d, u = {}, {}
print(u.get("input_tokens", ""), u.get("output_tokens", ""), u.get("cache_read_input_tokens", ""), d.get("total_cost_usd", ""))
' 2>/dev/null)
[[ -s "$CLAUDE_ERR" ]] && CLAUDE_OUTPUT+=$'\n'"$(cat "$CLAUDE_ERR")"
rm -f "$CLAUDE_ERR"

# Propagate the agent's self-declared verdict. `claude --print` exits 0 on any
# successful run regardless of what the agent concluded, so the operator run-
# tools (run-upgrade-advisor.sh etc.) couldn't tell REVIEW (queued/drafted)
# from GREEN. Agents end their report with a `NOS_AGENT_EXIT: N` sentinel; lift
# it into the process exit. Only ESCALATE a clean run — never mask a real
# claude failure (CLAUDE_EXIT already non-zero stays).
if [[ "$CLAUDE_EXIT" -eq 0 ]]; then
    # `|| true` is load-bearing: under `set -euo pipefail` a no-match grep makes
    # the whole $(...) pipeline exit non-zero, which aborts the script via the
    # _release_agent_lock EXIT trap BEFORE agent_run_end posts — orphaning the
    # session as status=running. Agents that emit no NOS_AGENT_EXIT sentinel
    # (conductor's prose report) hit this every run. Missing sentinel = treat as
    # exit 0 (empty AGENT_VERDICT), not a fatal pipefail.
    AGENT_VERDICT=$(printf '%s' "$CLAUDE_OUTPUT" \
        | grep -oE 'NOS_AGENT_EXIT:[[:space:]]*[0-9]+' | tail -1 \
        | grep -oE '[0-9]+$' || true)
    if [[ -n "$AGENT_VERDICT" && "$AGENT_VERDICT" -gt 0 ]]; then
        CLAUDE_EXIT="$AGENT_VERDICT"
        echo "INFO: agent self-declared review verdict (NOS_AGENT_EXIT=$AGENT_VERDICT)"
    fi
fi

echo "INFO: claude exited with code $CLAUDE_EXIT${TOK_IN:+ (tokens in=$TOK_IN out=$TOK_OUT cache=$TOK_CACHE cost=\$$COST)}"
if [[ -n "$CLAUDE_OUTPUT" ]]; then
    echo "$CLAUDE_OUTPUT" | tail -20
fi

# ── Wing: agent_run_end ───────────────────────────────────────────────────────

TS_END=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RESULT_SUMMARY=$(echo "${CLAUDE_OUTPUT:-}" | tail -3 | head -c 200)
# Same actor_action_id as start → events join in pulse_runs.actor_action_id.
# Canonical JSON via jq (see _post_wing_event docstring for the Bone HMAC
# canonicalization contract).
_post_wing_event "$(jq -a --sort-keys -nc \
    --arg ts "$TS_END" \
    --arg run_id "$RUN_ID" \
    --arg src "$AGENT_NAME" \
    --arg actor_id "$ACTOR_ID" \
    --arg action_id "$ACTOR_ACTION_ID" \
    --argjson exit_code "$CLAUDE_EXIT" \
    --arg summary "$RESULT_SUMMARY" \
    --argjson t_in "${TOK_IN:-0}" \
    --argjson t_out "${TOK_OUT:-0}" \
    --argjson t_cache "${TOK_CACHE:-0}" \
    '{ts:$ts, type:"agent_run_end", run_id:$run_id, source:$src,
      actor_id:$actor_id, actor_action_id:$action_id, acted_at:$ts,
      result:{exit_code:$exit_code, summary:$summary,
              tokens_input:$t_in, tokens_output:$t_out, tokens_cache_read:$t_cache}}')"

# ── A9 notification on non-zero exit ──────────────────────────────────────────
# Exit 1 = conductor reported actionable findings (operator review).
# Exit ≥2 = environment / auth / Wing error (operator must investigate).
# Channels resolved by Bone via the conductor agent profile's notification
# routing block (high/critical fan out to ntfy + mail per the routing).
if [[ "$CLAUDE_EXIT" -ne 0 ]]; then
    if [[ "$CLAUDE_EXIT" -ge 2 ]]; then
        NOTIF_SEV="critical"
    else
        NOTIF_SEV="high"
    fi
    # Capitalise first char portably — macOS ships bash 3.2, which lacks the
    # ${VAR^} (bash 4+) operator and errors "bad substitution" on every
    # non-zero-exit agent run (review verdicts fire this path).
    _agent_title="$(printf '%s' "${AGENT_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${AGENT_NAME:1}"
    NOTIF_TITLE="$_agent_title exit=$CLAUDE_EXIT (run=$RUN_ID)"
    NOTIF_BODY=$(printf '**run_id:** %s\n**task:** %s\n**exit:** %d\n\n```\n%s\n```' \
        "$RUN_ID" "${TASK_PROMPT:0:120}" "$CLAUDE_EXIT" "$(echo "${CLAUDE_OUTPUT:-}" | tail -10)")
    _post_wing_notification "$NOTIF_SEV" "$NOTIF_TITLE" "$NOTIF_BODY"
fi

echo "INFO: ${AGENT_NAME} finished (exit=$CLAUDE_EXIT)"
exit "$CLAUDE_EXIT"
