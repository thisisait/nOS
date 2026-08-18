#!/usr/bin/env bash
# =============================================================================
# nos-statusline.sh — one line of estate truth, for the tmux status bar.
#
# WHAT GOES IN IT, and why these and not others. The bar has room for numbers a
# person should not have to ask for, and the test for inclusion is: was this
# number wrong, unnoticed, for days? Two qualify by measurement:
#
#   reds     `tools/red-status.py` — the audit chain, failing jobs, the scan.
#            On 2026-08-18 two nightly jobs had been failing for two days.
#   inbox    unread CRITICAL/HIGH. That number was 68, oldest 24 days, while
#            every notification had been delivered correctly. Detection was
#            never the gap; a place to SEE the state was.
#
# WHAT IS DELIBERATELY OUT: anything that takes real time. `estate-status.py`
# measures at 2.17 s because it talks to git and the network — in a bar that
# refreshes every few seconds that is a background job hammering the host to
# tell you nothing new. The cheap readers are 0.11 s and 0.09 s.
#
# THE CACHE IS NOT AN OPTIMISATION, IT IS THE DESIGN. tmux re-runs
# `status-right` on its own interval; forking python each time would put the
# reader in the render path, so a slow reader becomes a laggy terminal and the
# fix everyone reaches for is to drop the reader. Instead: `--refresh` computes
# and writes, the bare call prints what was written, and the line carries its
# own AGE so a stale cache announces itself rather than passing as current.
#
# Usage:
#   tools/nos-statusline.sh              # print the cached line (instant)
#   tools/nos-statusline.sh --refresh    # recompute, write the cache, print
#
# Exit 0 always. A status bar that can fail is a status bar that shows an error
# where a number should be.
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${NOS_STATUSLINE_CACHE:-${HOME}/.nos/statusline}"
TTL=45            # seconds; older than this and the bare call recomputes

mkdir -p "$(dirname "$CACHE")" 2>/dev/null || true

refresh() {
    cd "$REPO_ROOT" 2>/dev/null || { printf 'nos: no repo\n'; return 0; }

    local reds inbox
    reds="$(python3 tools/red-status.py --json 2>/dev/null \
        | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get("red_count", "?"))
    print((d.get("inbox") or {}).get("critical_or_high", "?"))
except Exception:
    print("?"); print("?")' 2>/dev/null)"
    inbox="$(printf '%s\n' "$reds" | sed -n 2p)"
    reds="$(printf '%s\n' "$reds" | sed -n 1p)"

    # `?` means the reader could not answer. It must not render as 0 — absence
    # read as health is this estate's most-repeated defect.
    printf 'red %s · inbox %s' "${reds:-?}" "${inbox:-?}" > "$CACHE"
    cat "$CACHE"
    printf '\n'
}

case "${1:-}" in
    --refresh) refresh; exit 0 ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \?//'; exit 0 ;;
esac

# SELF-REFRESHING, so there is no background process to outlive or to die
# quietly. tmux calls this on its own interval; if the cache is older than the
# TTL this recomputes (0.11 s), otherwise it prints (instant). The reader is
# therefore in the render path at most once per TTL, which is the whole of what
# the cache was protecting against — and there is no second process whose death
# would freeze the bar at a comfortable number.
now=$(date +%s)
if [[ -f "$CACHE" ]]; then
    mtime=$(stat -f %m "$CACHE" 2>/dev/null || stat -c %Y "$CACHE" 2>/dev/null || echo 0)
else
    mtime=0
fi
age=$(( now - mtime ))

if [[ $age -ge $TTL ]]; then
    refresh
    exit 0
fi

cat "$CACHE"
printf '\n'
