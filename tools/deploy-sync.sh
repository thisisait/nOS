#!/usr/bin/env bash
# deploy-sync — make THIS checkout a clean, current mirror of its upstream,
# safely, before a converge. Ends the recurring pre-converge reconcile dance.
#
# THE ANNOYANCE THIS REMOVES. The nightly scan used to write
# remediation-queue.json + scan-state.json into the DEPLOY working tree.
# The live notebook is now ~/.nos/security/; git copies are the last promotion.
# This tool still snapshots the runtime notebook onto scan-data, and still
# discards leftover git dirt on those two promotion paths (they are never
# precious once the runtime notebook is recorded).
#
# WHAT IT DOES, in order, refusing on ANY doubt rather than clobbering:
#   1. fetch; read this checkout's position vs @{upstream}.
#   2. snapshot the runtime notebook onto the scan-data orphan branch.
#   3. DIRTY tree: a changed path that is NOT one of the two scan files -> STOP
#      (this tool only ever discards leftover scan promotion dirt). If only
#      those files are dirty, drop them — the live notebook is ~/.nos/security.
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

	# Leftover git dirt on the promotion paths. Live notebook is runtime;
	# snapshot already recorded it. Safe to drop.
	would "git checkout -- ${SCAN_PATHS[*]}   (drop leftover scan dirt; live notebook is ~/.nos/security)"
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
