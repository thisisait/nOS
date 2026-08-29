#!/usr/bin/env bash
# =============================================================================
# nos-cc.sh — the terminal control centre.
#
# One tmux session that shows what the estate IS, beside the places you act on
# it. Built 2026-08-18, after the surveyor's first completed ceremony named the
# gap itself: *"The control centre does not exist yet — this is the primary
# finding."* Every reader pane became a TUI on 2026-08-29 (`tools/nos-pane.py`):
# same rule, plus Ctrl+P to change what a pane shows and Enter to open a row.
#
# ── THE RULE THIS IS BUILT ON ────────────────────────────────────────────────
#
# A PANE SHOWS STATE, NOT SCROLLBACK. A tailed log looks healthy right up until
# its writer stops, and then it looks exactly the same. That is why the estate
# ran for two days with two failing nightly jobs while nothing appeared wrong:
# the notifications were delivered, correctly, on the first night — and a
# notification is an EVENT while red is a STATE. Every pane here re-runs a
# READER — `tools/nos-pane.py`, or `tools/nos-watch.sh` for a pane that is a
# plain command — and replaces its own contents, so a reader that stops
# answering says so instead of preserving the last good answer.
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
#
# Ctrl+P inside any reader pane swaps its content (tools/nos-pane.py --list).
# For the two SHELL panes there is no binding here on purpose: a tmux key table
# is GLOBAL, and this script does not write the operator's config. If you want
# one, it is one line in ~/.tmux.conf:
#   bind-key P display-menu -T "pane" r "red" "respawn-pane -k tools/nos-pane.py red" \
#                                    a "awaiting" "respawn-pane -k tools/nos-pane.py awaiting"
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

# ── ops: readers above, two free shells below ────────────────────────────────
#
#   ┌───────────────┬───────────────┐
#   │ what is red   │ agents        │   readers: state, re-run, never scrollback
#   │               ├───────────────┤
#   │               │ recent history│
#   ├───────────────┴───────────────┤
#   │ shell A       │ shell B       │   the operator's two free prompts
#   └───────────────┴───────────────┘
#
# TWO shells, because one was not enough in practice: the operator drives an
# agent session (claude / hermes / opencode) in one and still needs a prompt for
# the ordinary shell work that watching produces. NEITHER is started for them.
# That empty prompt is not laziness — it is what keeps the rule above true. A
# pane that launched an agent would be a pane that keeps one alive; a pane that
# offers a prompt is a place the operator starts one deliberately, and it ends
# when the run ends.
#
# `git log` earns its place up here for the same reason it has its own window:
# every other reader raises the question "what did we just do to ourselves". The
# glance lives here; the `code` window keeps the long form beside an editor.
#
# EVERY SPLIT HAPPENS BEFORE ANY send-keys. tmux renumbers panes by POSITION on
# each split, so a send-keys interleaved between splits addresses whichever pane
# later slid into that index — and the layout that results is not the one the
# code reads like. The indices below are the final ones, verified by building it.
# A SPLIT THAT FAILS MUST NOT BE SILENT. `set -uo pipefail` has no `-e`, so a
# refused `split-window` used to leave the script running happily: it went on to
# send-keys at pane indices that did not exist, exited 0, and produced a ONE-PANE
# `ops` window that the operator would see and the caller would call success.
# That is the estate's own standing rule — a step that cannot do its job must
# not exit 0 (docs/hidden_fees/07) — and it cost a CI red whose reason was
# nowhere in the log, because the only thing that noticed was a pane count.
# SIZES ARE `-l N%`, NEVER `-p N` (measured 2026-08-24). tmux 3.4 — the one
# ubuntu-24.04 ships, so the one CI runs — rejects `-p 32` outright with
# `size missing` (a 3.4 regression; 3.2a and 3.7c both accept it). `-l N%` is
# the documented spelling since 3.1 and works on every version the estate
# meets. This cost three days of CI red that no local run could reproduce.
_split() {
    local why="$1"; shift
    if ! tmux split-window "$@" 2>&1; then
        echo "nos-cc: split failed ($why): tmux split-window $*" >&2
        exit 3
    fi
}

tmux new-session -d -s "$SESSION" -n ops -c "$REPO_ROOT" || {
    echo "nos-cc: could not create session $SESSION" >&2; exit 3; }
_split "shell row"    -v -t "$SESSION:ops.0" -c "$REPO_ROOT" -l 32%
_split "-> shell B"   -h -t "$SESSION:ops.1" -c "$REPO_ROOT" -l 50%
_split "right column" -h -t "$SESSION:ops.0" -c "$REPO_ROOT" -l 45%
_split "-> history"   -v -t "$SESSION:ops.1" -c "$REPO_ROOT" -l 45%
# The operator's own queue, under `what is red` and beside the history. Red is
# what BROKE; this is what cannot proceed without a person — a judged proposal
# that never landed is not red, an agent that stopped to ask is working as
# designed, and a ruling amended after signing is neither. Until 2026-08-29
# nothing collected them, so each was found by remembering to look.
_split "-> awaiting"  -v -t "$SESSION:ops.0" -c "$REPO_ROOT" -l 38%

# EVERY READER PANE IS A TUI (2026-08-29). `nos-watch.sh` re-ran a reader and
# replaced the pane, which was right about STATE and offered nothing else: the
# content was fixed at layout time, a long table could not be read past its
# first screen, and a row could not be opened. `tools/nos-pane.py <id>` keeps
# the re-read and adds the two things the operator asked for — Ctrl+P swaps
# what THIS pane shows from the registry, Enter opens the row the reader
# returned. `--dump text` gives `tmux capture-pane -p` (and an LLM) the same
# rows the screen has, so the machine-readable view is not a second answer.
tmux send-keys -t "$SESSION:ops.0" "tools/nos-pane.py red" C-m
tmux send-keys -t "$SESSION:ops.1" "tools/nos-pane.py awaiting" C-m
tmux send-keys -t "$SESSION:ops.2" "tools/nos-pane.py agents" C-m
# ONE ROW PER COMMIT, and the pane can be scrolled now that it is a table —
# the decorated `git log` tail wrapped every long subject onto two lines and
# scrolled the NEWEST commits off the top, leaving the OLDEST three on screen.
# A pane that looked like recent history while showing the opposite.
tmux send-keys -t "$SESSION:ops.3" "tools/nos-pane.py history" C-m
tmux send-keys -t "$SESSION:ops.4" \
    "tools/elsewhere-status.py; clear" C-m
# ops.4 gets nothing typed into it at all. Deliberate: see above.

# ── stuck: the quiet half. red-status says what FAILS; this says what STOPPED ─
# Deliberately its own window rather than a pane: it is the view you open when
# nothing is on fire and you want to know what has been sitting still, and it is
# long enough that squeezing it beside something else would truncate the part
# that matters (the oldest rows are at the bottom of each list).
tmux new-window -t "=$SESSION" -n stuck -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:stuck" "tools/nos-pane.py stuck" C-m

# ── loop: the self-improvement ledger, which nothing else displays ───────────
tmux new-window -t "=$SESSION" -n loop -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:loop" "tools/nos-pane.py loop" C-m

# ── code: what changed, and the ability to go and look ───────────────────────
# `git log` is a READER too, and it is the one that answers "what did we just
# do to ourselves" — the question every other pane here raises. The editor is
# left unopened beside it: a window that launches vim on attach is a window you
# fight before you can read anything.
tmux new-window -t "=$SESSION" -n code -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:code" "tools/nos-pane.py history" C-m
_split "code editor"  -h -t "$SESSION:code" -c "$REPO_ROOT" -l 50%
tmux send-keys -t "$SESSION:code.1" "vim ." ""

# ── converge: its own window, because a converge is long and worth watching ──
# NOT auto-started. A converge is a deliberate act and this script is not the
# place that decides to run one; the command is left on the prompt unexecuted.
tmux new-window -t "=$SESSION" -n converge -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:converge" "nos" ""

# ── service: a plain shell, for everything that is not one of the above ──────
tmux new-window -t "=$SESSION" -n service -c "$REPO_ROOT"

tmux select-window -t "$SESSION:ops"
# Land on shell A — attaching should put the cursor where the operator types,
# not in a reader they would have to leave first.
tmux select-pane -t "$SESSION:ops.5"

# ── the bar ──────────────────────────────────────────────────────────────────
#
# Session-scoped, so attaching does not rewrite the operator's own tmux config
# for every other session on the host.
#
# UNANCHORED, AND THAT IS THE EXCEPTION (found 2026-08-18 by reading stderr).
# `set-option` resolves `-t` as a PANE, so `-t "=$SESSION"` is rejected outright
# — `no such session: =nos-cc`, four times, straight past a script that does not
# check. The bar was silently never set. The anchor rule stands everywhere it
# can: `has-session`, `kill-session` and `attach` all take it, and those are the
# ones where a prefix match costs someone their work. Setting a status option on
# the wrong session writes a status bar, which is recoverable by closing it.
#
# The `|| echo` is not decoration. The whole reason this needed finding is that
# tmux reported the failure and nothing was listening.
# `mouse on` is session-scoped, so it does not touch the operator's other
# sessions. Without it a pane's scrollback is unreachable without the prefix
# dance — measured 2026-08-28: the workflow pane rendered a 60-line tree into a
# 48-row pane and the top of it could not be reached at all.
for opt in "mouse on" \
           "status-interval 15" \
           "status-left #[bold] nOS #[default]" \
           "status-right #($REPO_ROOT/tools/nos-statusline.sh) #[dim]%H:%M" \
           "status-right-length 60"; do
    name="${opt%% *}"; value="${opt#* }"
    tmux set-option -t "$SESSION" "$name" "$value" \
        || echo "warning: could not set $name on $SESSION" >&2
done

if [[ $ATTACH -eq 1 ]]; then
    exec tmux attach -t "=$SESSION"
fi
echo "$SESSION built (detached) — attach with: tmux attach -t $SESSION"
