#!/usr/bin/env bash
# tools/promote-public.sh — promote a VETTED local change to a PUBLIC GitHub PR.
#
# The ONLY step in the local-first git flow that touches the public internet, and
# it is OPERATOR-RUN — it holds the GitHub credential (via gh). Agents NEVER call
# this; they only ever open local Gitea PRs (tools/recipe-pr.sh). See memory
# `local-first-git-topology`.
#
# Flow (Model A): an agent drafts a recipe → opens a Gitea PR → operator reviews +
# merges in Gitea. To share it upstream, the operator runs this on the host that
# has the GitHub remote + gh auth: it pushes the branch to GitHub and opens a PR.
# It NEVER merges (the GitHub PR is the public-review gate).
#
# DRY-RUN BY DEFAULT (operator doctrine: dry-run default + explicit confirm):
#   tools/promote-public.sh                      # show what would promote (current branch)
#   tools/promote-public.sh <branch>             # ... for <branch>
#   tools/promote-public.sh <branch> --open-pr   # push to GitHub + open the PR
#   tools/promote-public.sh <branch> --base master --open-pr
set -eu

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH=""
BASE="dev"
OPEN_PR=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --open-pr) OPEN_PR=1 ;;
    --base) shift; BASE="${1:-dev}" ;;
    -*) echo "[promote] unknown flag: $1"; exit 2 ;;
    *) BRANCH="$1" ;;
  esac
  shift
done
[ -n "$BRANCH" ] || BRANCH="$(git rev-parse --abbrev-ref HEAD)"

command -v gh >/dev/null 2>&1 || { echo "[promote] gh CLI not found (operator-only tool)"; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "[promote] gh not authenticated — run 'gh auth login'"; exit 2; }

# GitHub origin (the public trunk). Refuse if origin isn't a github.com remote —
# the local-first invariant is that only THIS step reaches GitHub.
ORIGIN_URL="$(git remote get-url origin 2>/dev/null || echo '')"
case "$ORIGIN_URL" in
  *github.com*) : ;;
  *) echo "[promote] origin is not a github.com remote (${ORIGIN_URL:-none}) — refusing"; exit 2 ;;
esac

git fetch -q origin "$BASE" 2>/dev/null || true
AHEAD="$(git rev-list --count "origin/${BASE}..${BRANCH}" 2>/dev/null || echo '?')"

echo "[promote] branch:  $BRANCH"
echo "[promote] base:    origin/$BASE  ($ORIGIN_URL)"
echo "[promote] commits ahead of origin/$BASE: $AHEAD"
git log --oneline "origin/${BASE}..${BRANCH}" 2>/dev/null | sed 's/^/    /' || true

if [ "$AHEAD" = "0" ]; then
  echo "[promote] nothing to promote (branch not ahead of origin/$BASE)"; exit 0
fi

if [ "$OPEN_PR" != 1 ]; then
  echo "[promote] DRY-RUN — pass --open-pr to push '$BRANCH' to GitHub and open the PR"
  exit 0
fi

echo "[promote] pushing $BRANCH → GitHub origin"
git push -u origin "$BRANCH"
gh pr create --base "$BASE" --head "$BRANCH" --fill \
  || { echo "[promote] gh pr create failed (a PR may already exist: gh pr view '$BRANCH')"; exit 1; }
echo "[promote] public PR opened against $BASE"
