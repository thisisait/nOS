#!/bin/bash
# ==============================================================================
# NOS Vulnerability Scanner — Iterative Scan Runner
# Managed by Ansible — do not edit manually
# Schedule: 2x daily via launchd (eu.thisisait.nos.vulnscan)
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

# Track G/seed: structured event emit. SCAN_RUN_ID threads through the
# whole batch so wing.db can aggregate per-batch finding counts under one
# timeline row. lib-jsonl.sh tees to ~/.nos/events/scan.jsonl + HMAC POSTs
# to Bone (when WING_EVENTS_HMAC_SECRET set; silent no-op otherwise).
export SCAN_RUN_ID="scan_$(date +%s)_$$"
# shellcheck source=lib-jsonl.sh
source "$(dirname "$0")/lib-jsonl.sh"

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
# Plain heredoc into a temp file — NOT $(cat <<EOF…): macOS /bin/bash 3.2
# cannot parse a heredoc inside command substitution and aborts with
# "unexpected EOF while looking for matching )" (live pulse run 2026-06-11;
# the exec-bit fix let the script run for the first time and exposed this).
PROMPT_FILE=$(mktemp -t nos-scan-prompt.XXXXXX)
cat > "$PROMPT_FILE" <<PROMPT_EOF
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

# ── Emit scan.batch_started event ────────────────────────────────────────────

# Convert BATCH (newline-separated) → JSON array for the event payload.
BATCH_JSON=$(echo "$BATCH" | jq -R . | jq -sc .)
emit_event "scan.batch_started" "$(jq -nc \
    --argjson components "$BATCH_JSON" \
    --argjson batch_size "$BATCH_SIZE" \
    --arg probe "$PROBE_NAME" \
    --argjson cycle "$SCAN_CYCLE" \
    '{components:$components, batch_size:$batch_size, attack_probe:$probe, scan_cycle:$cycle}'
)" >> "$LOG_FILE"

# ── Dispatch Claude Code ──────────────────────────────────────────────────────
#
# THE AGENT-RUN MUTEX, missing here until 2026-08-06. The LOCK_FILE taken at
# the top of this script guards against a second SCAN; it says nothing about a
# second claude. Meanwhile pulse-run-agent.sh described its own mkdir mutex as
# "the single chokepoint every agent goes through" — and this line was outside
# it, so a Pulse agent firing near 02:00 could run concurrently with the scan,
# which is the arrangement that crashed every participant in May.
#
# Wait, do not skip: nobody is watching at 02:00, and a scan that silently
# declined is exactly the absence-reads-as-calm shape this estate keeps
# finding. 10 minutes, then refuse loudly and let the exit code carry it.
#
# The helper installs its own EXIT trap, so the combined trap below is
# re-armed AFTER acquiring — otherwise this script's LOCK_FILE would leak.
# Resolved from $0, the way lib-jsonl.sh above is — NOT from REPO_DIR, whose
# default ($(dirname $0)/..) points at files/, not the repo root, and only
# works because the launchd job overrides it.
# shellcheck source=../anatomy/scripts/agent-run-lock.sh
source "$(dirname "$0")/../anatomy/scripts/agent-run-lock.sh"
if ! nos_agent_lock_acquire "vulnscan:${SCAN_RUN_ID}" 600 cli; then
    log "ERROR: another claude-CLI agent holds the agent-run lock — scan not dispatched"
    emit_event "scan.batch_refused" '{"reason":"agent-run lock held"}' >> "$LOG_FILE"
    exit 2
fi
trap 'nos_agent_lock_release; cleanup' EXIT

log "Dispatching Claude Code scan..."
SCAN_STARTED_AT=$(date +%s)

SCAN_RC=0
claude --dangerously-skip-permissions -p - < "$PROMPT_FILE" \
    --output-format text \
    2>>"$LOG_FILE" || SCAN_RC=$?
rm -f "$PROMPT_FILE"

# ── Update scan state ─────────────────────────────────────────────────────────
#
# ONLY on a scan that actually ran. Until 2026-08-01 the non-zero exit was
# swallowed into a WARN line and the loop below stamped last_checked,
# last_cve_scan, last_attack_probe and status="scanned" for every component
# regardless — so a scan that never happened (claude rate-limited, out of
# session, crashed, refusing) left scan-state.json claiming all five components
# had just been CVE-scanned and attack-probed, with no new queue rows and a
# Pulse run recorded as exit 0.
#
# The freshness it fabricated was not merely cosmetic: drift-watch.sh reads
# last_full_scan_age_hours, so the fake timestamp is exactly what keeps the
# staleness branch quiet. The watcher built to make scan rot loud was being fed
# the value that hid it. (Its pending_critical branch still fires independently
# — what the fake freshness defeats is the "the pipeline stopped producing
# findings at all" signal, which is the one nothing else can raise.)
if [ "$SCAN_RC" -ne 0 ]; then
    log "ERROR: Claude Code scan exited $SCAN_RC — NOT stamping components as scanned"
    for COMPONENT in $BATCH; do
        jq --arg comp "$COMPONENT" --arg ts "$TIMESTAMP" '
          .components[$comp].status = "scan_failed"
          | .components[$comp].last_scan_attempt = $ts
        ' "$STATE_FILE" > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE"
    done
    emit_event "scan.batch_failed" "$(jq -nc \
        --argjson components "$BATCH_JSON" --argjson rc "$SCAN_RC" \
        '{components:$components, exit_code:$rc}')" >> "$LOG_FILE"
    log "=== NOS Vulnerability Scan FAILED ==="
    exit 1
fi

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
    # `now | todate` MUST be parenthesised. `|` is jq's pipe, so
    # `.last_full_scan = now | todate` assigns the epoch and then pipes the whole
    # OBJECT into todate, which dies with "strftime/1 requires parsed datetime
    # inputs". The write then never happened: scan_cycle froze at 16 and
    # PROBE_INDEX (= scan_cycle % 8) pinned the attack probe to index 0 forever,
    # so 7 of the 8 probes had not run since the freeze. Exit code stayed 0
    # throughout — the error only ever appeared on stderr.
    if jq '.scan_cycle += 1 | .last_full_scan = (now | todate)' "$STATE_FILE" > "${STATE_FILE}.tmp"; then
        mv "${STATE_FILE}.tmp" "$STATE_FILE"
    else
        rm -f "${STATE_FILE}.tmp"
        log "ERROR: could not advance scan_cycle — the attack probe will not rotate"
    fi
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

# ── Emit scan.batch_done event ───────────────────────────────────────────────
# Closes the batch in wing.db's timeline. duration_s lets us track scan
# latency over time (Grafana panel can spot a misbehaving Claude Code rev).
SCAN_DURATION=$(( $(date +%s) - SCAN_STARTED_AT ))
PENDING_AFTER=$(jq '[.items[] | select(.status == "pending")] | length' \
                  "${SECURITY_DIR}/remediation-queue.json" 2>/dev/null || echo "null")
emit_event "scan.batch_done" "$(jq -nc \
    --argjson components "$BATCH_JSON" \
    --argjson duration_s "$SCAN_DURATION" \
    --argjson pending_after "$PENDING_AFTER" \
    --argjson cycle_complete "$([ "$PENDING" -eq 0 ] && echo true || echo false)" \
    '{components:$components, duration_s:$duration_s, pending_total_after:$pending_after, cycle_complete:$cycle_complete}'
)" >> "$LOG_FILE"

log "=== NOS Vulnerability Scan finished ==="
