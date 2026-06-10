#!/usr/bin/env bash
# tools/sync-trunk-to-gitlab.sh — keep the GitLab agent forge's trunk
# (dev/master) fresh from GitHub. OPERATOR-HOST only — this host is the only
# bridge between GitHub (origin) and GitLab (the MR review surface, T32.2).
# The forge project is a normal writable repo (created EMPTY by pazny.gitlab
# post-forge.yml), so trunk sync is an explicit fetch-from-GitHub →
# push-to-GitLab here. Run after a GitHub trunk update, or on a cron/Pulse
# cadence. Twin of tools/sync-trunk-to-gitea.sh.
#
# FAST-FORWARD ONLY — it never force-pushes, so it can never clobber agent
# branches or a GitLab `dev` that's ahead (Model A: when an agent merge has
# landed in GitLab but not yet on GitHub, the GitLab trunk leads; promote it to
# GitHub first — tools/promote-public.sh — then this sync FF-converges).
#
#   tools/sync-trunk-to-gitlab.sh            # sync dev + master
#   tools/sync-trunk-to-gitlab.sh dev        # just dev
#
# `set -eu` only — NO pipefail (grep|sed|head config chains return 1 on no-match).
set -eu

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BRANCHES=("$@")
[ "${#BRANCHES[@]}" -gt 0 ] || BRANCHES=(dev master)

# Refuse if origin isn't GitHub — the sync pulls FROM the public trunk.
ORIGIN_URL="$(git remote get-url origin 2>/dev/null || echo '')"
case "$ORIGIN_URL" in
  *github.com*) : ;;
  *) echo "[sync] origin is not a github.com remote (${ORIGIN_URL:-none}) — refusing"; exit 2 ;;
esac

# ── GitLab config discovery (mirrors tools/recipe-pr.sh) ──────────────────────
yaml_lookup() {
  local key="$1"; shift; local v
  for f in "$@"; do
    [ -f "$f" ] || continue
    v=$(grep -h -E "^${key}:" "$f" 2>/dev/null \
        | sed -n -E 's/^[^:]+:[[:space:]]*"?([^"#]*[^"#[:space:]])"?[[:space:]]*(#.*)?$/\1/p' \
        | grep -vE '\{\{' | head -1 || true)
    [ -n "${v:-}" ] && { printf '%s' "$v"; return 0; }
  done
  return 0
}

TOKEN="${GITLAB_TOKEN:-}"
[ -n "$TOKEN" ] || TOKEN="$(yaml_lookup gitlab_api_token credentials.yml config.yml "$HOME/.nos/secrets.yml")"
DOMAIN="${GITLAB_DOMAIN:-}"
[ -n "$DOMAIN" ] || DOMAIN="$(yaml_lookup gitlab_domain credentials.yml config.yml)"
if [ -z "$DOMAIN" ]; then
  TENANT="$(yaml_lookup tenant_domain config.yml default.config.yml)"
  [ -n "$TENANT" ] && DOMAIN="gitlab.${TENANT}"
fi
OWNER="$(yaml_lookup gitlab_nos_repo_owner config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"
[ -n "$OWNER" ] || OWNER="root"
NAME="$(yaml_lookup gitlab_nos_repo_name config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"
[ -n "$NAME" ] || NAME="nOS"

if [ -z "$TOKEN" ] || [ -z "$DOMAIN" ]; then
  echo "[sync] missing GITLAB_TOKEN/gitlab_api_token or gitlab_domain — is the forge provisioned? (gitlab_agent_forge=true)"; exit 2
fi
GITLAB_URL="https://oauth2:${TOKEN}@${DOMAIN}/${OWNER}/${NAME}.git"

echo "[sync] fetching GitHub origin: ${BRANCHES[*]}"
git fetch -q origin "${BRANCHES[@]}"

rc=0
for b in "${BRANCHES[@]}"; do
  echo "[sync] $b → GitLab ${OWNER}/${NAME} (fast-forward only)"
  # Push the freshly-fetched GitHub ref into the GitLab branch. No --force:
  # a non-FF (GitLab trunk ahead via an un-promoted agent merge) fails loudly
  # and is left for the operator to promote + reconcile.
  if ! git push "$GITLAB_URL" "refs/remotes/origin/${b}:refs/heads/${b}" 2>/dev/null; then
    echo "[sync]   $b NOT fast-forward — GitLab is ahead (un-promoted agent merge?); promote it first, then re-sync"
    rc=1
  fi
done
exit "$rc"
