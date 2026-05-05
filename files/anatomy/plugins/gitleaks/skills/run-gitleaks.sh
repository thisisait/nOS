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
if ! gitleaks git \
        --source="$SCAN_DIR" \
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

HTTP_BODY=$(echo "$HTTP_RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$HTTP_RESPONSE" | tail -n 1)

if [[ "$HTTP_CODE" != "201" ]]; then
    echo "ERROR: Wing ingest failed (HTTP $HTTP_CODE): $HTTP_BODY" >&2
    exit 2
fi

INSERTED=$(echo "$HTTP_BODY" | jq -r '.inserted // 0')
SKIPPED=$(echo "$HTTP_BODY"  | jq -r '.skipped  // 0')

echo "INFO: Wing ingest complete — inserted=$INSERTED skipped=$SKIPPED"

if [[ "$INSERTED" -gt 0 ]]; then
    echo "WARN: $INSERTED new secret finding(s) — operator review needed"
    exit 1
fi

# All filtered findings were already known to Wing (skipped = dedup'd).
exit 0
