#!/usr/bin/env bash
# ==============================================================================
# files/vuln-scan/lib-jsonl.sh — structured event emit for the vuln-scan pipeline
#
# Sourced by scan-runner.sh. Provides a single function `emit_event` that:
#   1. Synthesizes a canonical JSON event with ts / type / run_id + extras
#   2. Appends to ~/.nos/events/scan.jsonl (operator-tailable, LLM-readable)
#   3. POSTs HMAC-signed to Bone /api/v1/events when WING_EVENTS_HMAC_SECRET
#      is set (best-effort — never fails the caller; offline scans still
#      produce the JSONL and run-time stdout)
#
# This is the contract seed for the bones & wings refactor's Pulse class:
# every agentic runner (vuln-scan, conductor, future inspektor / librarian /
# scout) emits the same shape. wing.db can then aggregate scans alongside
# playbook events under one timeline.
#
# HMAC signature compatibility:
#   message = "${ts_epoch}.${canonical_json_body}"
#   signature = HMAC-SHA256(message, secret)  hex-encoded
#   headers: X-Wing-Timestamp, X-Wing-Signature
# Matches files/bone/events.py:verify_hmac and the Python callback plugin.
#
# Track G/seed work — see docs/active-work.md.
# ==============================================================================

set -uo pipefail

# Caller may pre-export SCAN_RUN_ID to thread the same id across all events
# in a batch. Default to a unique-per-process id.
: "${SCAN_RUN_ID:=scan_$(date +%s)_$$}"
: "${WING_EVENTS_URL:=http://127.0.0.1:8099/api/v1/events}"
# WING_EVENTS_HMAC_SECRET — when unset, HMAC POST is skipped silently.

_jsonl_dir() {
    local d="${HOME:-/tmp}/.nos/events"
    mkdir -p "$d" 2>/dev/null
    echo "$d"
}

# emit_event <type> [extra_json]
#   <type>       — must be one of the allowed types in files/bone/events.py
#                   (scan.batch_started | scan.finding_recorded | scan.batch_done | …)
#   [extra_json] — optional JSON object whose keys are merged into the event
#                  (e.g. '{"components":["traefik","gitea"],"batch_size":5}')
emit_event() {
    local event_type="${1:-}"
    local extra_json="${2:-{\}}"
    if [[ -z "$event_type" ]]; then
        echo "emit_event: missing type arg" >&2
        return 1
    fi
    if ! command -v jq >/dev/null 2>&1; then
        # No jq → can't synthesize JSON cleanly. Print a noisy stderr line
        # so the operator notices, then bail. Don't fail the caller.
        echo "emit_event: jq not on PATH — skipping (event=$event_type)" >&2
        return 0
    fi

    local ts event_json jsonl
    ts="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    event_json="$(jq -cn \
        --arg ts "$ts" \
        --arg type "$event_type" \
        --arg run_id "$SCAN_RUN_ID" \
        --argjson extra "$extra_json" \
        '{ts: $ts, type: $type, run_id: $run_id} + $extra')"

    # Hop 1 — JSONL (always)
    jsonl="$(_jsonl_dir)/scan.jsonl"
    printf '%s\n' "$event_json" >> "$jsonl"

    # Hop 2 — stdout (so dispatch capture / interactive runs can grep)
    printf '%s\n' "$event_json"

    # Hop 3 — HMAC POST to Bone (best-effort)
    if [[ -n "${WING_EVENTS_HMAC_SECRET:-}" ]]; then
        if ! command -v curl >/dev/null 2>&1; then
            return 0
        fi
        if ! command -v openssl >/dev/null 2>&1; then
            return 0
        fi
        local body ts_epoch sig
        body="$(printf '%s' "$event_json" | jq -cS '.')"
        ts_epoch="$(date +%s)"
        sig="$(printf '%s.%s' "$ts_epoch" "$body" | \
              openssl dgst -sha256 -hmac "${WING_EVENTS_HMAC_SECRET}" -hex 2>/dev/null | \
              awk '{print $NF}')"
        curl -fsS -m 3 -X POST "$WING_EVENTS_URL" \
             -H "Content-Type: application/json" \
             -H "X-Wing-Timestamp: $ts_epoch" \
             -H "X-Wing-Signature: $sig" \
             -d "$body" >/dev/null 2>&1 || true
    fi
}

# Sanity self-check when sourced with --self-test
if [[ "${1:-}" == "--self-test" ]]; then
    emit_event "scan.batch_started" '{"components":["self-test"],"batch_size":1}'
    echo "self-test: see $(_jsonl_dir)/scan.jsonl" >&2
fi
