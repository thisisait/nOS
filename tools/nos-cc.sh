#!/usr/bin/env bash
# =============================================================================
# nos-cc.sh — the terminal control centre.
#
# One tmux session that shows what the estate IS, beside the places you act on
# it. Built 2026-08-18, after the surveyor's first completed ceremony named the
# gap itself: *"The control centre does not exist yet — this is the primary
# finding."*
#
# ── THE RULE THIS IS BUILT ON ────────────────────────────────────────────────
#
# A PANE SHOWS STATE, NOT SCROLLBACK. A tailed log looks healthy right up until
# its writer stops, and then it looks exactly the same. That is why the estate
# ran for two days with two failing nightly jobs while nothing appeared wrong:
# the notifications were delivered, correctly, on the first night — and a
# notification is an EVENT while red is a STATE. Every pane here re-runs a
# READER (`tools/nos-watch.sh`) and replaces its own contents, so a reader that
# stops answering says so instead of preserving the last good answer.
#
# ── PERSISTENT VISIBILITY, NOT PERSISTENT AGENTS ─────────────────────────────
#
# There is no pane that keeps an agent alive. Agent runs are bounded on purpose
# — a session token ceiling, a wall clock, a per-iteration call cap — and an
# agent that runs forever is a runaway with a nicer name. What persists here is
# the VIEW of them: `tools/agent-status.py` renders the sessions table, which is
# where the estate's most expensive unread fact lived (fifteen bound sessions,
# zero completions, discovered after five supervised runs).
#
# ── WHAT IT WILL NOT DO ──────────────────────────────────────────────────────
#
# Touch a session it did not create. The operator already keeps `nos`,
# `converge` and `convergence` open with work in them; a tool that "sets up your
# terminal" by killing panes is a tool used once. This owns exactly the session
# named below, attaches if it already exists, and never kills a window.
#
# Usage:
#   tools/nos-cc.sh            # create or attach
#   tools/nos-cc.sh --rebuild  # kill ONLY this session and rebuild it
#   tools/nos-cc.sh --print    # show the layout without touching tmux
# =============================================================================
set -uo pipefail

SESSION="${NOS_CC_SESSION:-nos-cc}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REBUILD=0
ATTACH=1

for arg in "$@"; do
    case "$arg" in
        --rebuild) REBUILD=1 ;;
        # Build and leave it detached. Exists so the layout can be TESTED —
        # a setup script whose only exit is `exec attach` can only be checked
        # by a human looking at it, which is how layout bugs ship.
        --no-attach) ATTACH=0 ;;
        --print)
            sed -n '2,40p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        -h|--help) sed -n '2,42p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

command -v tmux >/dev/null 2>&1 || { echo "tmux is not installed" >&2; exit 2; }

if [[ $REBUILD -eq 1 ]] && tmux has-session -t "=$SESSION" 2>/dev/null; then
    # `=` anchors the name so `nos-cc` cannot match `nos` or `nos-cc-old`. A
    # prefix match here would kill the operator's own sessions, which is the one
    # unrecoverable thing this script could do.
    tmux kill-session -t "=$SESSION"
fi

if tmux has-session -t "=$SESSION" 2>/dev/null; then
    if [[ $ATTACH -eq 1 ]]; then
        exec tmux attach -t "=$SESSION"
    fi
    echo "$SESSION already exists — attach with: tmux attach -t $SESSION"
    exit 0
fi

W="$REPO_ROOT/tools/nos-watch.sh"

# ── ops: what is red, and what the agents are doing ──────────────────────────
tmux new-session -d -s "$SESSION" -n ops -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:ops" \
    "$W --interval 30 --title 'what is red' -- tools/red-status.py" C-m

# Right column: agents above, an operator shell below. The shell is deliberately
# the smaller half — this is a place to WATCH from, and the big terminals for
# doing work are the operator's own sessions.
tmux split-window -h -t "$SESSION:ops" -c "$REPO_ROOT" -p 45
tmux send-keys -t "$SESSION:ops.1" \
    "$W --interval 20 --title 'agents' -- tools/agent-status.py --limit 8" C-m

tmux split-window -v -t "$SESSION:ops.1" -c "$REPO_ROOT" -p 40

# ── loop: the self-improvement ledger, which nothing else displays ───────────
tmux new-window -t "=$SESSION" -n loop -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:loop" \
    "$W --interval 120 --title 'weakness -> proposal -> verdict' -- tools/loop-status.py" C-m

# ── converge: its own window, because a converge is long and worth watching ──
# NOT auto-started. A converge is a deliberate act and this script is not the
# place that decides to run one; the command is left on the prompt unexecuted.
tmux new-window -t "=$SESSION" -n converge -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:converge" "nos" ""

# ── service: a plain shell, for everything that is not one of the above ──────
tmux new-window -t "=$SESSION" -n service -c "$REPO_ROOT"

tmux select-window -t "$SESSION:ops"
tmux select-pane -t "$SESSION:ops.2"

# ── the bar ──────────────────────────────────────────────────────────────────
# Session-scoped (`set -t`), so attaching does not rewrite the operator's own
# tmux config for every other session on the host.
tmux set -t "=$SESSION" status-interval 15
tmux set -t "=$SESSION" status-left "#[bold] nOS #[default]"
tmux set -t "=$SESSION" status-right "#($REPO_ROOT/tools/nos-statusline.sh) #[dim]%H:%M"
tmux set -t "=$SESSION" status-right-length 60

if [[ $ATTACH -eq 1 ]]; then
    exec tmux attach -t "=$SESSION"
fi
echo "$SESSION built (detached) — attach with: tmux attach -t $SESSION"
