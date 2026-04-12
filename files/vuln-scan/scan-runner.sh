#!/bin/bash
# ==============================================================================
# NOS Vulnerability Scanner — Iterative Scan Runner
# Managed by Ansible — do not edit manually
# Schedule: 2x daily via launchd (com.devboxnos.vulnscan)
#
# Logic:
#   1. Read scan-state.json for component timestamps
#   2. Pick N oldest-checked components (oldest_first strategy)
#   3. Dispatch Claude Code with scan-prompt.md for the batch
#   4. Update scan-state.json with results
# ==============================================================================

set -euo pipefail

SECURITY_DIR="${VULNSCAN_SECURITY_DIR:-$(dirname "$0")/../docs/llm/security}"
REPO_DIR="${VULNSCAN_REPO_DIR:-$(dirname "$0")/..}"
BATCH_SIZE="${VULNSCAN_BATCH_SIZE:-5}"
STATE_FILE="${SECURITY_DIR}/scan-state.json"
PROMPT_FILE="${REPO_DIR}/files/vuln-scan/scan-prompt.md"
LOG_FILE="${SECURITY_DIR}/scan.log"
LOCK_FILE="/tmp/nos-vulnscan.lock"

# ── Helpers ───────────────────────────────────────────────────────────────────

log() {
    echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"
}

cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# ── Lock check (prevent concurrent runs) ─────────────────────────────────────

if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        log "SKIP: Another scan is running (PID $LOCK_PID)"
        exit 0
    fi
    log "WARN: Stale lock file removed"
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"

# ── Preflight ─────────────────────────────────────────────────────────────────

if [ ! -f "$STATE_FILE" ]; then
    log "ERROR: scan-state.json not found at $STATE_FILE"
    exit 1
fi

if ! command -v claude &>/dev/null; then
    log "ERROR: claude CLI not found in PATH"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    log "ERROR: jq not found in PATH"
    exit 1
fi

log "=== NOS Vulnerability Scan started ==="
log "Batch size: $BATCH_SIZE"

# ── Select batch (oldest_first strategy) ──────────────────────────────────────

# Extract components sorted by last_checked (null = epoch 0 = highest priority)
BATCH=$(jq -r '
  .components | to_entries
  | sort_by(.value.last_checked // "1970-01-01T00:00:00Z")
  | .[0:'"$BATCH_SIZE"']
  | .[].key
' "$STATE_FILE")

if [ -z "$BATCH" ]; then
    log "No components to scan"
    exit 0
fi

BATCH_LIST=$(echo "$BATCH" | tr '\n' ',' | sed 's/,$//')
log "Selected batch: $BATCH_LIST"

# ── Determine attack probe cycle ─────────────────────────────────────────────

SCAN_CYCLE=$(jq -r '.scan_cycle // 0' "$STATE_FILE")
PROBE_INDEX=$((SCAN_CYCLE % 8))
PROBE_NAME=$(jq -r ".attack_probe_schedule[$PROBE_INDEX].name // \"unknown\"" "$STATE_FILE")
log "Scan cycle: $SCAN_CYCLE, Attack probe: $PROBE_NAME"

# ── Build dynamic prompt ─────────────────────────────────────────────────────

TIMESTAMP=$(date -Iseconds)
DYNAMIC_PROMPT=$(cat <<PROMPT_EOF
# NOS Vulnerability Scan — Batch Run

**Timestamp:** $TIMESTAMP
**Scan cycle:** $SCAN_CYCLE
**Components:** $BATCH_LIST
**Attack probe focus:** $PROBE_NAME

## Instructions

You are the NOS Security Auditor. This is a scheduled iterative scan.

### For each component ($BATCH_LIST):

1. **CVE Scan**: Search for HIGH/CRITICAL CVEs from the last 12 months
   - Use web search: "{component} CVE 2025 2026 security vulnerability"
   - Check OSV.dev and GitHub Security Advisories
   - Only report verified findings with source links

2. **Attack Probe ($PROBE_NAME)**: Run the designated probe type
   - Analyze the component's docker-compose template and nginx vhost
   - Document specific attack vectors and their feasibility
   - Rate each vector: exploitable / theoretical / mitigated

3. **Output**: Append findings to existing files in $SECURITY_DIR/:
   - Update remediation-queue.json with new items
   - Update scan-state.json timestamps for scanned components
   - If critical finding: prepend to 2026-04-08-vuln-report.md

### Rules:
- Do NOT fabricate CVE IDs
- Cite every source
- Mark confidence level (high/medium/low)
- Read existing findings first to avoid duplicates
- Update scan-state.json component timestamps after scanning
PROMPT_EOF
)

# ── Dispatch Claude Code ──────────────────────────────────────────────────────

log "Dispatching Claude Code scan..."

echo "$DYNAMIC_PROMPT" | claude --dangerously-skip-permissions -p - \
    --output-format text \
    2>>"$LOG_FILE" || {
    log "WARN: Claude Code scan returned non-zero exit"
}

# ── Update scan state ─────────────────────────────────────────────────────────

log "Updating scan state..."

for COMPONENT in $BATCH; do
    jq --arg comp "$COMPONENT" --arg ts "$TIMESTAMP" --arg probe "$PROBE_NAME" '
      .components[$comp].last_checked = $ts
      | .components[$comp].last_cve_scan = $ts
      | .components[$comp].last_attack_probe = $ts
      | .components[$comp].status = "scanned"
    ' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
done

# ── Check if full cycle complete ──────────────────────────────────────────────

PENDING=$(jq '[.components | to_entries[] | select(.value.last_checked == null)] | length' "$STATE_FILE")

if [ "$PENDING" -eq 0 ]; then
    jq '.scan_cycle += 1 | .last_full_scan = now | todate' "$STATE_FILE" > "${STATE_FILE}.tmp" \
        && mv "${STATE_FILE}.tmp" "$STATE_FILE"
    NEW_CYCLE=$(jq -r '.scan_cycle' "$STATE_FILE")
    log "Full cycle complete! Starting cycle $NEW_CYCLE"
fi

# ── Update rotation hint ──────────────────────────────────────────────────────

NEXT_BATCH=$(jq -r '
  .components | to_entries
  | sort_by(.value.last_checked // "1970-01-01T00:00:00Z")
  | .[0:'"$BATCH_SIZE"']
  | [.[].key]
' "$STATE_FILE")

jq --argjson nb "$NEXT_BATCH" '.rotation.next_batch = $nb' "$STATE_FILE" > "${STATE_FILE}.tmp" \
    && mv "${STATE_FILE}.tmp" "$STATE_FILE"

log "Next batch: $(echo "$NEXT_BATCH" | jq -r 'join(", ")')"
log "=== NOS Vulnerability Scan finished ==="
