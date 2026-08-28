#!/bin/bash
# agent-run-lock.sh — the one mutex every agent run goes through.
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
# WHY IT IS A SLOT DIRECTORY (Q12, 2026-08-28). The May crash was a claude-CLI
# crash. An AgentKit run is in-process PHP against wing.db and does not share
# that failure mode, so a global N=1 mutex was charging the ops plane for a
# defect it does not have. The lock is now N=3 SLOTS under ONE path:
#
#   kind=agentkit -> takes ONE slot   (up to 3 run abreast)
#   kind=cli      -> takes ALL slots  (meets nobody — the surviving invariant)
#
# ONE lock path, still. A second lock for the CLI path is precisely the defect
# in the paragraph above: two locks cannot compare claims, so the CLI would
# once again believe it was exclusive while an AgentKit run was live.
#
# What makes three abreast safe is not the slot count but the WAL writer's
# busy timeout — pdo_sqlite opens wing.db with busy_timeout=60000ms (measured
# 2026-08-28), so concurrent slot-holders QUEUE at the writer lock instead of
# erroring SQLITE_BUSY. Drop that and N=3 becomes three racing writers.
#
# macOS ships no `flock`, so each slot is an atomic `mkdir` (POSIX-atomic on
# every filesystem) with a PID-liveness check to reclaim a slot left behind by
# a crashed run. Release uses rmdir + rm -f — never `rm -rf` — so a misset
# NOS_AGENT_LOCK_DIR cannot widen the blast radius.
#
# Usage:
#   source .../agent-run-lock.sh
#   nos_agent_lock_acquire "<owner-label>" [wait_seconds] [cli|agentkit]
#   ... spawn claude / run the agent ...
# Release is automatic: acquire installs an EXIT trap. Kind defaults to `cli`,
# the exclusive one: a caller that has not said what it is gets the old law.
#
# Exit 2 on refusal, matching pulse-run-agent.sh's existing contract. NOT 0:
# a run that could not do its job must not report success, or the night the
# lock is permanently stuck reads as a quiet estate.

NOS_AGENT_LOCK="${NOS_AGENT_LOCK_DIR:-${HOME:-/nonexistent}/.nos/agent-run.lock}"
NOS_AGENT_LOCK_SLOTS="${NOS_AGENT_LOCK_SLOTS:-3}"
NOS_AGENT_LOCK_HELD=()

nos_agent_lock_release() {
    local slot
    for slot in ${NOS_AGENT_LOCK_HELD[@]+"${NOS_AGENT_LOCK_HELD[@]}"}; do
        rm -f "$slot/owner" 2>/dev/null || true
        rmdir "$slot" 2>/dev/null || true
    done
    NOS_AGENT_LOCK_HELD=()
    # Only ever removes an EMPTY parent — another holder's slot keeps it.
    rmdir "$NOS_AGENT_LOCK" 2>/dev/null || true
}

# _nos_agent_slot_take <slot-dir> <owner-label> — 0 if the slot is now ours.
_nos_agent_slot_take() {
    local slot="$1" label="$2" owner pid
    if ! mkdir "$slot" 2>/dev/null; then
        owner=$(cat "$slot/owner" 2>/dev/null || true)
        pid="${owner%% *}"
        # A slot whose owner is gone is debris, not a claim.
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        echo "WARN: reclaiming stale agent lock ${slot##*/} (owner '${owner:-none}' not alive)" >&2
        rm -f "$slot/owner" 2>/dev/null || true
        rmdir "$slot" 2>/dev/null || true
        mkdir "$slot" 2>/dev/null || return 1
    fi
    printf '%s %s %s\n' "$$" "$label" "$(date -u +%FT%TZ)" > "$slot/owner"
    NOS_AGENT_LOCK_HELD+=("$slot")
    return 0
}

_nos_agent_lock_owners() {
    cat "$NOS_AGENT_LOCK"/slot.*/owner 2>/dev/null | tr '\n' ';'
}

# nos_agent_lock_acquire <owner-label> [wait_seconds] [cli|agentkit]
nos_agent_lock_acquire() {
    local label="${1:-unknown}"
    local wait_s="${2:-0}"
    local kind="${3:-cli}"
    local want=1 waited=0 got i

    [[ "$kind" == "cli" ]] && want="$NOS_AGENT_LOCK_SLOTS"

    while true; do
        mkdir -p "$NOS_AGENT_LOCK"
        got=0
        for (( i = 1; i <= NOS_AGENT_LOCK_SLOTS; i++ )); do
            if (( got >= want )); then break; fi
            _nos_agent_slot_take "$NOS_AGENT_LOCK/slot.$i" "$kind:$label" && got=$(( got + 1 ))
        done
        if (( got >= want )); then break; fi

        # All-or-nothing: a partial claim parked here is a deadlock with the
        # next acquirer. ponytail: two CLI acquirers can livelock trading
        # slots; both are bounded by wait_s and refuse loudly. Add a ticket
        # slot (monotonic counter) only if that is ever observed.
        nos_agent_lock_release

        if (( waited >= wait_s )); then
            echo "ERROR: another nOS agent run holds the lock — $(_nos_agent_lock_owners)" >&2
            echo "       ${kind}:${label} needs ${want}/${NOS_AGENT_LOCK_SLOTS} slots." >&2
            echo "       claude-CLI agents must run sequentially (concurrent runs crash mid-run)." >&2
            echo "       Waited ${waited}s. Remove ${NOS_AGENT_LOCK} if it is stale." >&2
            return 2
        fi
        sleep 5
        waited=$(( waited + 5 ))
    done

    trap 'nos_agent_lock_release' EXIT
    if (( waited > 0 )); then
        echo "agent lock acquired after ${waited}s of waiting" >&2
    fi
    return 0
}
