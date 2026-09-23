#!/bin/bash
# agent-session-claim.sh — who gets to BE the pulse run?
#
# WHY THIS FILE EXISTS, measured 2026-09-23. On 2026-08-29 run-agent.sh started
# adopting PULSE_RUN_ID as the agent session uuid, so "the run and the session
# are one row". That is right for a job that runs ONE agent. The invoice vision
# pipeline runs two agents per page over six pages — twelve calls inside one
# pulse run — and every call after the first hit
#
#   UNIQUE constraint failed: agent_sessions.uuid
#
# so `loop:vision-bench` died rc=2 on every image and reported the wrong cause
# ("is qwen2.5vl:7b pulled?"). It had been red for weeks.
#
# The fix keeps the good half: the FIRST agent in a run still adopts the run's
# uuid, so the common single-agent job keeps its zero-hop lineage. Every later
# agent self-allocates and stays linked through `--trigger-id`, which is the
# column that exists for exactly this.
#
# The claim is an atomic `mkdir` — the same primitive agent-run-lock.sh uses,
# for the same reason (macOS ships no flock, mkdir is POSIX-atomic everywhere).
# Unlike the lock it is NEVER released: a claim means "this run's uuid is
# already spent", which stays true until the run is over. Claims are cheap
# empty directories under TMPDIR and are swept by age on the next claim.
#
# Usage:
#   source .../agent-session-claim.sh
#   if nos_agent_session_claim "$PULSE_RUN_ID"; then  # first agent of this run
#       ... adopt the run id as the session uuid ...
#   fi

: "${NOS_AGENT_SESSION_CLAIM_DIR:=${TMPDIR:-/tmp}/nos-agent-session-claims}"
#: Sweep horizon in minutes. A pulse run outlives neither.
: "${NOS_AGENT_SESSION_CLAIM_TTL_MIN:=1440}"

nos_agent_session_claim() {
    local run_id="$1"
    [[ -n "$run_id" ]] || return 1
    mkdir -p "$NOS_AGENT_SESSION_CLAIM_DIR" 2>/dev/null || return 1
    # Sweep before claiming: a day-old claim belongs to a run that is long gone,
    # and an unswept directory would grow forever on a host that never reboots.
    find "$NOS_AGENT_SESSION_CLAIM_DIR" -mindepth 1 -maxdepth 1 -type d \
         -mmin "+$NOS_AGENT_SESSION_CLAIM_TTL_MIN" -exec rmdir {} + 2>/dev/null
    # `mkdir` succeeds for exactly one caller — that caller is the run's session.
    mkdir "$NOS_AGENT_SESSION_CLAIM_DIR/$run_id" 2>/dev/null
}
