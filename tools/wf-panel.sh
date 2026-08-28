#!/usr/bin/env bash
# wf-panel.sh — put the workflow tree in the nos-cc panel, and nowhere else.
#
# WHY A SCRIPT AND NOT A send-keys IN nos-cc.sh. The pane must stay a SHELL the
# operator can scroll and type in — the tree is content pushed INTO it, not a
# reader loop that owns it. `tools/nos-watch.sh` deliberately clears its pane on
# every tick, which is right for a state reader and wrong here: a definition is
# read by scrolling, and clearing it every 30s makes that impossible.
#
# Idempotent and safe when the session is absent: no tmux, no session, or no
# such pane are all reported and exit 0 — this is a convenience, and a missing
# terminal must not fail a hook that runs on every edit.
#
# Usage: tools/wf-panel.sh [<script.js>]      (default: the newest one)
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${NOS_CC_SESSION:-nos-cc}"
# `=` anchors the target: tmux matches sessions by PREFIX, so an unanchored
# name reaches the operator's own sessions (nos-cc.sh carries the same rule).
PANE="${NOS_CC_WF_PANE:-=$SESSION:ops.4}"

command -v tmux >/dev/null 2>&1 || { echo "wf-panel: no tmux — nothing to update"; exit 0; }
tmux has-session -t "=$SESSION" 2>/dev/null || { echo "wf-panel: session $SESSION not running"; exit 0; }
tmux list-panes -t "$PANE" >/dev/null 2>&1 || { echo "wf-panel: no pane $PANE"; exit 0; }

OUT="${TMPDIR:-/tmp}/nos-wf-tree.txt"
ARGS=(--latest); [[ $# -gt 0 && -n "${1:-}" ]] && ARGS=("$1")
if ! "$REPO_ROOT/tools/workflow-tree.py" "${ARGS[@]}" >"$OUT" 2>&1; then
    echo "wf-panel: workflow-tree.py failed — the pane keeps its last render" >&2
fi
# `clear` then `cat`: the pane's own scrollback holds the result, so copy-mode
# scrolls it. respawn-pane would kill the shell the operator is typing in.
tmux send-keys -t "$PANE" "clear; cat '$OUT'" C-m
