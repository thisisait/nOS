#!/usr/bin/env bash
# =============================================================================
# run-gitleaks.sh — gitleaks secret-scan skill (Anatomy A7, 2026-05-06)
#
# Called by Pulse subprocess runner as the nightly-scan job.
# Expects env vars (set via pulse_jobs.env_json):
#   WING_API_URL         — Wing base URL  (default: http://127.0.0.1:9000)
#   WING_API_TOKEN       — Bearer token for Wing API  (required)
#   NOS_SCAN_DIR         — Directory to scan  (default: repo root via $0)
#   GITLEAKS_MIN_SEVERITY — Minimum severity to ingest  (default: medium)
#   PULSE_RUN_ID         — Set by Pulse daemon; used as scan_id in Wing
#
# Exit codes:
#   0 — scan complete, no findings above threshold (or all already known)
#   1 — scan complete, new findings ingested (operator attention needed)
#   2 — scan or Wing API error (check stderr)
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

WING_API_URL="${WING_API_URL:-http://127.0.0.1:9000}"
WING_API_TOKEN="${WING_API_TOKEN:-}"
SCAN_DIR="${NOS_SCAN_DIR:-$(cd "$(dirname "$0")/../../../../.." && pwd)}"
MIN_SEVERITY="${GITLEAKS_MIN_SEVERITY:-medium}"
SCAN_ID="${PULSE_RUN_ID:-manual-$(date +%s)}"

SEVERITY_ORDER="critical high medium low info"

if [[ -z "$WING_API_TOKEN" ]]; then
    echo "ERROR: WING_API_TOKEN is not set" >&2
    exit 2
fi

if ! command -v gitleaks &>/dev/null; then
    echo "ERROR: gitleaks not found in PATH" >&2
    exit 2
fi

if ! command -v jq &>/dev/null; then
    echo "ERROR: jq not found in PATH" >&2
    exit 2
fi

# ── Severity filter ───────────────────────────────────────────────────────────

# Returns 0 (true) if severity $1 >= threshold $2, else 1.
severity_gte() {
    local sev="$1" threshold="$2"
    local pos_sev pos_threshold i=0
    for s in $SEVERITY_ORDER; do
        [[ "$s" == "$sev" ]]       && pos_sev=$i
        [[ "$s" == "$threshold" ]] && pos_threshold=$i
        (( i++ ))
    done
    [[ "${pos_sev:-99}" -le "${pos_threshold:-99}" ]]
}

# ── Mask a secret ─────────────────────────────────────────────────────────────

mask_secret() {
    local s="$1"
    local len="${#s}"
    if (( len <= 8 )); then
        echo "****"
        return
    fi
    echo "${s:0:4}...${s: -4}"
}

# ── Run gitleaks ──────────────────────────────────────────────────────────────

TMPFILE="$(mktemp /tmp/gitleaks-report-XXXXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

echo "INFO: scanning $SCAN_DIR (min_severity=$MIN_SEVERITY, scan_id=$SCAN_ID)"

# --exit-code 0: we handle exit signalling ourselves based on ingest result.
# --no-banner: keep stdout clean for structured output.
# --report-path: write JSON to temp file.
# Scan the git history (not just working tree) for maximum coverage.
#
# gitleaks 8.x: the repo/source is a POSITIONAL arg (`gitleaks git [flags]
# [repo]`); the old `--source=` flag was removed in the 8.18 CLI redesign and
# returns "unknown flag", which made every scan exit 2 → no findings ever
# ingested, no notification ever emitted (Wing Inbox stayed empty).
if ! gitleaks git "$SCAN_DIR" \
        --report-format=json \
        --report-path="$TMPFILE" \
        --exit-code=0 \
        --no-banner \
        2>/dev/null; then
    echo "ERROR: gitleaks exited non-zero unexpectedly" >&2
    exit 2
fi

TOTAL_RAW=$(jq 'if . == null then 0 else length end' "$TMPFILE")
echo "INFO: gitleaks found $TOTAL_RAW raw findings"

if [[ "$TOTAL_RAW" -eq 0 ]]; then
    echo "INFO: clean — no findings, nothing to ingest"
    exit 0
fi

# ── Transform to Wing ingest format ──────────────────────────────────────────

# Map gitleaks' native JSON array → Wing's findings array.
# gitleaks fields: RuleID, Description, StartLine, File, Commit,
#                  Author, Date, Secret, Fingerprint, Tags, Severity
# Severity in gitleaks ≥ v8: present on the rule; may be empty string.
FINDINGS_JSON=$(jq --arg scan_dir "$SCAN_DIR" --arg min_sev "$MIN_SEVERITY" '
    # Severity rank: lower index = more severe
    def sev_rank: {"critical":0,"high":1,"medium":2,"low":3,"info":4};
    def normalize_sev(s):
        (s // "high" | ascii_downcase) as $s
        | if $s == "" then "high"
          elif $s == "critical" then "critical"
          elif $s == "high" then "high"
          elif $s == "medium" then "medium"
          elif $s == "low" then "low"
          else "info"
          end;
    def mask(s):
        (s // "") as $s
        | if ($s | length) <= 8 then "****"
          else ($s[0:4] + "..." + $s[-4:])
          end;

    [.[] |
        (normalize_sev(.Severity // .Tags[0])) as $sev |
        # Apply severity filter
        select((sev_rank[$sev] // 4) <= (sev_rank[$min_sev] // 2)) |
        {
            fingerprint:   (.Fingerprint // ""),
            rule_id:       (.RuleID      // "unknown"),
            description:   (.Description // null),
            secret_masked: mask(.Secret),
            file_path:     (.File        // ""),
            line_start:    (.StartLine   // 0),
            commit:        (.Commit      // null),
            author:        (.Author      // null),
            date:          (.Date        // null),
            severity:      $sev,
            repo_path:     $scan_dir
        }
    ]
' "$TMPFILE")

FILTERED_COUNT=$(echo "$FINDINGS_JSON" | jq 'length')
echo "INFO: $FILTERED_COUNT findings at or above $MIN_SEVERITY severity"

if [[ "$FILTERED_COUNT" -eq 0 ]]; then
    echo "INFO: all findings below threshold — nothing to ingest"
    exit 0
fi

# ── POST to Wing ──────────────────────────────────────────────────────────────

INGEST_PAYLOAD=$(jq -n \
    --arg scan_id "$SCAN_ID" \
    --argjson findings "$FINDINGS_JSON" \
    '{scan_id: $scan_id, findings: $findings}')

HTTP_RESPONSE=$(curl -sS -w "\n%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $WING_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$INGEST_PAYLOAD" \
    "$WING_API_URL/api/v1/gitleaks_findings" 2>&1)

# sed '$d' (drop last line) — NOT `head -n -1`: negative counts are GNU-only,
# BSD/macOS head dies with "illegal line count" (live pulse failure 2026-06-10).
HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed '$d')
HTTP_CODE=$(echo "$HTTP_RESPONSE" | tail -n 1)

if [[ "$HTTP_CODE" != "201" ]]; then
    echo "ERROR: Wing ingest failed (HTTP $HTTP_CODE): $HTTP_BODY" >&2
    exit 2
fi

INSERTED=$(echo "$HTTP_BODY" | jq -r '.inserted // 0')
SKIPPED=$(echo "$HTTP_BODY"  | jq -r '.skipped  // 0')

echo "INFO: Wing ingest complete — inserted=$INSERTED skipped=$SKIPPED"

# ── Notification fanout (Anatomy A9, 2026-05-16) ──────────────────────────────
# When new findings landed, emit ONE summary notification per scan run.
# Channels are resolved by Bone's routing fallback against gitleaks'
# severity block (on_critical → wing-inbox+ntfy+mail; on_high → +ntfy;
# on_medium → inbox only). Skipping when WING_EVENTS_HMAC_SECRET unset
# (manual runs without the plist env still ingest, just don't notify).

if [[ "$INSERTED" -gt 0 && -n "${WING_EVENTS_HMAC_SECRET:-}" ]]; then
    # Highest severity among the newly inserted findings — drives routing.
    MAX_SEV=$(echo "$FINDINGS_JSON" | jq -r '
        def rank: {"critical":0,"high":1,"medium":2,"low":3,"info":4};
        map(rank[.severity]) | min as $best
        | if $best == 0 then "critical"
          elif $best == 1 then "high"
          elif $best == 2 then "medium"
          elif $best == 3 then "low"
          else "info" end
    ')
    # Build top-3 finding markdown for the template context. The plugin
    # manifest's `notification.templates.new_findings` resolves
    # `${top_findings_md}` against this value (and `${count}`/`${scan_dir}`
    # against the other context keys). Bone renders the strings via
    # string.Template.safe_substitute at insert time — no per-emitter
    # title-body building boilerplate.
    TOP_FINDINGS_MD=$(echo "$FINDINGS_JSON" | jq -r '
        (.[0:3] | map("- `\(.severity)` " + .rule_id + " @ " + .file_path + ":" + (.line_start|tostring)) | join("\n")) +
        (if (. | length) > 3 then "\n\n…and " + ((. | length) - 3 | tostring) + " more." else "" end)
    ')
    NOTIF_BODY=$(jq -n \
        --arg sev "$MAX_SEV" \
        --arg tpl "new_findings" \
        --arg count "$INSERTED" \
        --arg scan_id "$SCAN_ID" \
        --arg scan_dir "$SCAN_DIR" \
        --arg top "$TOP_FINDINGS_MD" \
        '{severity: $sev, template: $tpl,
          context: {count: $count, scan_dir: $scan_dir, top_findings_md: $top},
          origin_plugin: "gitleaks", actor_id: "plugin:gitleaks",
          actor_action_id: $scan_id,
          metadata: {scan_dir: $scan_dir, scan_id: $scan_id}}')
    # Canonical form (sort_keys + compact) so Bone's HMAC verifier matches.
    # Bone re-canonicalizes the parsed dict via Python json.dumps with
    # separators=(',',':') + sort_keys=True before computing the expected
    # signature. See files/anatomy/scripts/pulse-run-agent.sh's
    # _post_wing_event docstring for the live 2026-05-17 401 incident.
    NOTIF_BODY_COMPACT=$(echo "$NOTIF_BODY" | jq --sort-keys -c .)
    TS=$(date +%s)
    SIG=$(printf '%s.%s' "$TS" "$NOTIF_BODY_COMPACT" \
          | openssl dgst -sha256 -hmac "$WING_EVENTS_HMAC_SECRET" \
          | awk '{print $NF}')   # openssl 3.x emits just <hex>; 1.x emits "(stdin)= <hex>"
    BONE_URL="${BONE_API_URL:-http://127.0.0.1:9000}"
    NOTIF_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "X-Wing-Timestamp: $TS" \
        -H "X-Wing-Signature: $SIG" \
        -H "Content-Type: application/json" \
        -d "$NOTIF_BODY_COMPACT" \
        "$BONE_URL/api/v1/notifications" 2>&1 || echo "000")
    if [[ "$NOTIF_CODE" == "200" || "$NOTIF_CODE" == "201" ]]; then
        echo "INFO: notification emitted (severity=$MAX_SEV)"
    else
        echo "WARN: notification POST returned HTTP $NOTIF_CODE — findings ingested OK, audit only" >&2
    fi
fi

if [[ "$INSERTED" -gt 0 ]]; then
    echo "WARN: $INSERTED new secret finding(s) — operator review needed"
    exit 1
fi

# All filtered findings were already known to Wing (skipped = dedup'd).
exit 0
