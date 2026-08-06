#!/bin/bash
# agent-run-lock.sh — the one mutex every claude-CLI spawn goes through.
#
# WHY THIS FILE EXISTS. Firing several claude-CLI agents at once made all
# participants die mid-run: only agent_run_start landed, never agent_run_end
# (2026-05-27; memory agent-two-runtime-session-gap). `pulse-run-agent.sh`
# grew a mkdir mutex for that and described itself as "the single chokepoint
# every agent goes through".
#
# It was not. `files/vuln-scan/scan-runner.sh` spawns claude at 02:00 without
# ever touching this lock — it holds a DIFFERENT one (/tmp/nos-vulnscan.lock),
# which stops a second scan and knows nothing about agents. Two locks, one
# invariant, nothing comparing them: the estate's signature defect, found by
# the 2026-08-06 edge survey. Extracted here so the law has one implementation
# and both callers demonstrably share it.
#
# macOS ships no `flock`, so this is an atomic `mkdir` lock (POSIX-atomic on
# every filesystem) with a PID-liveness check to reclaim a lock left behind by
# a crashed run. Release uses rmdir + rm -f — never `rm -rf` — so a misset
# NOS_AGENT_LOCK_DIR cannot widen the blast radius.
#
# Usage:
#   source .../agent-run-lock.sh
#   nos_agent_lock_acquire "<owner-label>" [wait_seconds]   # 0 = do not wait
#   ... spawn claude ...
# Release is automatic: acquire installs an EXIT trap.
#
# Exit 2 on refusal, matching pulse-run-agent.sh's existing contract. NOT 0:
# a run that could not do its job must not report success, or the night the
# lock is permanently stuck reads as a quiet estate.

NOS_AGENT_LOCK="${NOS_AGENT_LOCK_DIR:-${HOME:-/nonexistent}/.nos/agent-run.lock}"

nos_agent_lock_release() {
    rm -f "$NOS_AGENT_LOCK/owner" 2>/dev/null || true
    rmdir "$NOS_AGENT_LOCK" 2>/dev/null || true
}

# nos_agent_lock_acquire <owner-label> [wait_seconds]
nos_agent_lock_acquire() {
    local label="${1:-unknown}"
    local wait_s="${2:-0}"
    local waited=0

    mkdir -p "$(dirname "$NOS_AGENT_LOCK")"

    while true; do
        if mkdir "$NOS_AGENT_LOCK" 2>/dev/null; then
            break
        fi

        local owner pid
        owner=$(cat "$NOS_AGENT_LOCK/owner" 2>/dev/null || true)
        pid="${owner%% *}"

        # A lock whose owner is gone is debris, not a claim.
        if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
            echo "WARN: reclaiming stale agent lock (owner '${owner:-none}' not alive)" >&2
            nos_agent_lock_release
            continue
        fi

        if (( waited >= wait_s )); then
            echo "ERROR: another nOS agent run holds the lock — ${owner}." >&2
            echo "       claude-CLI agents must run sequentially (concurrent runs crash mid-run)." >&2
            echo "       Waited ${waited}s. Remove ${NOS_AGENT_LOCK} if it is stale." >&2
            return 2
        fi
        sleep 5
        waited=$(( waited + 5 ))
    done

    printf '%s %s %s\n' "$$" "$label" "$(date -u +%FT%TZ)" > "$NOS_AGENT_LOCK/owner"
    trap 'nos_agent_lock_release' EXIT
    if (( waited > 0 )); then
        echo "agent lock acquired after ${waited}s of waiting" >&2
    fi
    return 0
}
