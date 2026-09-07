#!/usr/bin/env bash
# deploy-sync — make THIS checkout a clean, current mirror of its upstream,
# safely, before a converge. Ends the recurring pre-converge reconcile dance.
#
# THE ANNOYANCE THIS REMOVES. The nightly security scan writes
# remediation-queue.json + scan-state.json into the working tree and nothing
# commits them — by design (tools/scan-state-snapshot.py: the dirt is scan
# output `dev` has not been given yet). But the DEPLOY checkout — the one you
# converge from — is the same tree, so that by-design dirt, plus any local
# scan-state commit, collides with the converge preflight's need for a clean
# origin/dev (tasks/preflight-checkout-current.yml). And it re-collides on every
# origin advance, so each converge became: stash / pull / pop, or promote, by
# hand. The preflight is a look-never-touch gate and must stay one; this is the
# explicit "prepare the checkout" step that gate presumes you already ran.
#
# WHAT IT DOES, in order, refusing on ANY doubt rather than clobbering:
#   1. fetch; read this checkout's position vs @{upstream}.
#   2. snapshot the current scan output onto the scan-data orphan branch, so
#      nothing the scan produced is lost whatever step 3/4 drops.
#   3. DIRTY tree: a changed path that is NOT one of the two scan files -> STOP
#      (this tool only ever discards scan output). If the scan files are dirty,
#      `scan-state-snapshot --status` decides: DISCARDABLE (upstream already
#      carries >= them) -> drop them; PRECIOUS (upstream is missing findings) ->
#      STOP and tell you to promote + push first.
#   4. AHEAD of upstream: commits ahead that touch ONLY the scan paths are scan
#      drift (their content is on scan-data) -> reset to upstream. A commit that
#      touches anything else is real work -> STOP, push it first.
#   5. reset HEAD to upstream (a no-op fast-forward when there was nothing
#      ahead). Now HEAD == upstream, clean -> the converge runs the code you
#      pushed.
#
# Idempotent: on an already-clean, already-current checkout it fetches,
# snapshots (no-op) and exits 0. `--dry-run` reports what it WOULD do and
# touches nothing. Run it from the checkout you converge from.
#
# Exit: 0 synced (or already clean+current); 2 refused (real dirt/divergence you
# must resolve); 3 refused (scan output upstream lacks — promote it first).
set -euo pipefail

SCAN_PATHS=(
	"docs/llm/security/remediation-queue.json"
	"docs/llm/security/scan-state.json"
)

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
say() { printf '%s\n' "$*"; }
refuse() { printf '\n[deploy-sync] REFUSED: %s\n' "$1" >&2; exit "${2:-2}"; }
would() { if [ "$DRY" = 1 ]; then say "  [dry] would: $*"; else say "  → $*"; fi; }

git rev-parse --git-dir >/dev/null 2>&1 || refuse "not a git repository (run me from the deploy checkout)"

say "[deploy-sync] fetching…"
git -c fetch.parallel=1 fetch --quiet origin || refuse "git fetch failed — cannot compare against upstream"

UP="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)" \
	|| refuse "no upstream for the current branch — nothing to mirror"
BRANCH="$(git symbolic-ref --quiet --short HEAD)" || refuse "detached HEAD — checkout a branch first"
BEHIND="$(git rev-list --count "HEAD..$UP")"
AHEAD="$(git rev-list --count "$UP..HEAD")"
say "[deploy-sync] $BRANCH is $BEHIND behind, $AHEAD ahead of $UP"

# ── 2. Preserve scan output on the orphan branch, unconditionally. ───────────
if [ "$DRY" = 1 ]; then
	say "  [dry] would: tools/scan-state-snapshot.py  (record scan output on scan-data)"
else
	say "  → snapshotting scan output to scan-data (nothing lost)"
	python3 "$SCRIPT_DIR/scan-state-snapshot.py" || refuse "scan-state-snapshot failed — not touching the tree"
fi

# ── 3. Dirty tree: scan files only, and only if discardable. ─────────────────
DIRTY="$(git status --porcelain --untracked-files=no | awk '{print $2}')"
if [ -n "$DIRTY" ]; then
	while IFS= read -r p; do
		[ -z "$p" ] && continue
		keep=0
		for s in "${SCAN_PATHS[@]}"; do [ "$p" = "$s" ] && keep=1; done
		[ "$keep" = 1 ] || refuse "working-tree change to '$p' is not scan output — commit or stash it yourself, then re-run"
	done <<<"$DIRTY"

	# Only scan files are dirty. Are they precious (upstream lacks them)?
	set +e
	python3 "$SCRIPT_DIR/scan-state-snapshot.py" --status "${UP#*/}" >/dev/null 2>&1
	st=$?
	set -e
	if [ "$st" = 3 ]; then
		refuse "the working tree holds scan findings $UP does not — promote them first:
    tools/scan-state-snapshot.py --promote   # then review + commit + push to $UP
  (they are safe on the scan-data branch meanwhile)" 3
	elif [ "$st" != 0 ]; then
		refuse "scan-state-snapshot --status could not decide ($st) — resolve by hand rather than risk discarding findings" 3
	fi
	would "git checkout -- ${SCAN_PATHS[*]}   (drop scan dirt; superseded by $UP)"
	[ "$DRY" = 1 ] || git checkout -- "${SCAN_PATHS[@]}"
fi

# ── 4. Ahead commits: scan paths only, or it is real work. ───────────────────
if [ "$AHEAD" -gt 0 ]; then
	CHANGED="$(git diff --name-only "$UP...HEAD")"
	while IFS= read -r p; do
		[ -z "$p" ] && continue
		ok=0
		for s in "${SCAN_PATHS[@]}"; do [ "$p" = "$s" ] && ok=1; done
		[ "$ok" = 1 ] || refuse "a local commit ahead of $UP touches '$p' — that is real work, not scan drift. Push or rebase it first (its content is preserved on scan-data regardless)."
	done <<<"$CHANGED"
	say "[deploy-sync] the $AHEAD commit(s) ahead touch only scan output — preserved on scan-data, safe to drop"
fi

# ── 5. HEAD := upstream. A no-op ff when nothing was ahead. ──────────────────
if [ "$AHEAD" -gt 0 ] || [ "$BEHIND" -gt 0 ]; then
	would "git reset --hard $UP"
	[ "$DRY" = 1 ] || git reset --hard "$UP"
else
	say "[deploy-sync] already current."
fi

say "[deploy-sync] $([ "$DRY" = 1 ] && echo 'DRY RUN — nothing changed.' || echo "done — $BRANCH is a clean mirror of $UP; converge away.")"
