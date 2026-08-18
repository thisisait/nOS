#!/usr/bin/env bash
# =============================================================================
# nos-watch.sh — render a reader's CURRENT OUTPUT on an interval, in place.
#
# The primitive the whole terminal control centre is built on, and it exists to
# enforce one rule: A PANE SHOWS STATE, NOT SCROLLBACK.
#
# A tailed log looks healthy right up until its writer stops, and then it looks
# exactly the same — the last line just stays there. That is the same defect as
# a healthcheck that answers without touching its database
# (docs/hidden_fees/02), and it is the reason this estate spent two days with
# two nightly jobs failing while every surface looked fine. So a pane here
# re-runs a READER and replaces its own contents; if the reader stops answering,
# the pane says so instead of preserving the last good answer.
#
# WHY NOT `watch(1)`: it is not on a stock macOS, and its screen handling fights
# tmux's own. This is ten lines of the same idea with a header that carries the
# thing `watch` omits — WHEN the answer was taken, and whether taking it failed.
#
# Usage:
#   tools/nos-watch.sh [--interval N] [--title T] -- <command> [args…]
#
# Example:
#   tools/nos-watch.sh --interval 30 --title 'reds' -- tools/red-status.py
#
# Ctrl-C leaves the pane at its last render, which is correct: a person who
# stopped the refresh is looking at something.
# =============================================================================
set -uo pipefail

INTERVAL=30
TITLE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval) INTERVAL="${2:?--interval needs a value}"; shift 2 ;;
        --title)    TITLE="${2:?--title needs a value}"; shift 2 ;;
        --)         shift; break ;;
        -h|--help)  sed -n '2,28p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *)          echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

[[ $# -gt 0 ]] || { echo "nothing to run — pass a command after --" >&2; exit 2; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

# Colour only when the pane is a terminal, so a piped run stays diffable.
if [[ -t 1 ]]; then
    DIM=$'\033[2m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    DIM=""; RED=""; RESET=""
fi

while :; do
    # Render to a buffer FIRST, then clear and print. Clearing before a slow
    # command leaves the pane blank for the duration, which reads as "dead".
    out="$("$@" 2>&1)"
    rc=$?
    stamp="$(date '+%H:%M:%S')"

    printf '\033[H\033[2J'          # home + clear
    if [[ $rc -eq 0 ]]; then
        printf '%s%s  ·  %s  ·  every %ss%s\n\n' "$DIM" "${TITLE:-$1}" "$stamp" "$INTERVAL" "$RESET"
    else
        # A reader that FAILED must not leave its last good answer on screen —
        # that is the scrollback lie in miniature.
        printf '%s%s  ·  %s  ·  READER FAILED rc=%s%s\n\n' \
            "$RED" "${TITLE:-$1}" "$stamp" "$rc" "$RESET"
    fi
    printf '%s\n' "$out"

    sleep "$INTERVAL" || break
done
