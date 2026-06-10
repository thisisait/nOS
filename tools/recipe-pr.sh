#!/usr/bin/env bash
# tools/recipe-pr.sh — validate an upgrade recipe and (optionally) open a PR/MR
# on the LOCAL forge (never GitHub). The agent-authoring safety boundary:
# upgrade-architect drafts a recipe into upgrades/<service>.yml; this validates
# it through the authoritative gates and, with --open-pr, branches + commits +
# pushes to the local forge and opens a review request for a human to review +
# merge. It NEVER merges and NEVER force-pushes. The public GitHub PR is a
# SEPARATE, operator-run step (tools/promote-public.sh) — the agent loop stays
# off the public internet.
#
# FORGE TARGET (T32.2, 2026-06-10): default comes from `nos_agent_forge` in
# config.yml / default.config.yml (repo default: "gitlab" — GitLab MERGE
# REQUESTS are the operator review surface; the Gitea oauth2 source row kept
# vanishing → SSO 500 → operator locked out of the Gitea UI). Override per-run
# with --forge gitea|gitlab.
#
# DRY-RUN BY DEFAULT (operator doctrine: dry-run default + explicit confirm):
#   tools/recipe-pr.sh <service>             # validate only — no git, no push
#   tools/recipe-pr.sh <service> --open-pr   # validate, then branch+commit+push+PR/MR
#   tools/recipe-pr.sh <service> --open-pr --base master    # base branch (default: dev)
#   tools/recipe-pr.sh <service> --open-pr --forge gitea    # explicit forge override
#
# Forge config is auto-discovered (same pattern as tools/nos-push):
#   gitlab: token  — GITLAB_TOKEN env, else gitlab_api_token in credentials.yml /
#                    config.yml / ~/.nos/secrets.yml (pazny.gitlab post-forge.yml)
#           domain — GITLAB_DOMAIN env, else gitlab_domain, else gitlab.<tenant_domain>
#           owner/name — gitlab_nos_repo_owner (root) / gitlab_nos_repo_name (nOS)
#   gitea:  token  — GITEA_TOKEN env, else gitea_api_token (same lookup chain)
#           domain — GITEA_DOMAIN env, else gitea_domain, else git.<tenant_domain>
#           owner/name — gitea_nos_repo_owner ($USER) / gitea_nos_repo_name (nOS)
#
# DEPENDS: the forge repo must be WRITABLE — pazny.gitlab post-forge.yml
# (gitlab_agent_forge=true) / pazny.gitea post-forge.yml (gitea_agent_forge=true).
# The validate-only path works with no forge at all.
#
# `set -eu` only — NO pipefail (same as tools/nos-push): the grep|sed|head
# config-parse chains legitimately return 1 on no-match, which pipefail would
# propagate and abort under set -e. The explicit fallbacks handle missing values.
set -eu

# Cleanup on ANY exit path: remove the curl temp file AND switch the operator's
# live tree back to the original ref if we branched (review 2026-06-10: the
# script used to strand the tree on fix/recipe-*, and a multi-recipe architect
# run stacked each MR on the previous branch). $$ is fixed at parse time.
SWITCHED=0
ORIG_REF=""
cleanup() {
  rm -f "/tmp/recipe-pr-resp.$$"
  if [ "${SWITCHED:-0}" = 1 ] && [ -n "${ORIG_REF:-}" ]; then
    git switch -q "$ORIG_REF" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SERVICE=""
OPEN_PR=0
BASE="dev"
FORGE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --open-pr) OPEN_PR=1 ;;
    --base) shift; BASE="${1:-dev}" ;;
    --forge) shift; FORGE="${1:-}" ;;
    -*) echo "[recipe-pr] unknown flag: $1"; exit 2 ;;
    *) SERVICE="$1" ;;
  esac
  shift
done
[ -n "$SERVICE" ] || { echo "usage: tools/recipe-pr.sh <service> [--open-pr] [--base <branch>] [--forge gitlab|gitea]"; exit 2; }

RECIPE="upgrades/${SERVICE}.yml"
[ -f "$RECIPE" ] || { echo "[recipe-pr] no recipe at $RECIPE"; exit 2; }

# ── 1. Validate through the authoritative recipe gates ────────────────────────
echo "[recipe-pr] validating $RECIPE"
if command -v yamllint >/dev/null 2>&1; then
  if yamllint -f parsable "$RECIPE" | grep -qE ':[0-9]+:[0-9]+: \[error\]'; then
    echo "[recipe-pr] yamllint errors in $RECIPE"; exit 1
  fi
fi
python3 -m pytest -q \
  tests/upgrades/test_schema_validation.py \
  tests/upgrades/test_from_regex_matching.py \
  tests/upgrades/test_template_vars_resolvable.py \
  || { echo "[recipe-pr] recipe gates FAILED — fix before opening a PR"; exit 1; }
echo "[recipe-pr] OK — $RECIPE passes schema + from_regex + template-var gates"

if [ "$OPEN_PR" != 1 ]; then
  echo "[recipe-pr] validate-only (pass --open-pr to branch+commit+push+open the review request)"
  exit 0
fi

# ── 2. Forge config discovery (mirrors tools/nos-push) ────────────────────────
# yaml_lookup <key> <file>... — first plain-scalar value, skipping {{ jinja }}.
# sed -n + /p: print ONLY on a successful substitution — the plain `sed s///`
# passed the whole line through for empty-quoted values (`key: ""`), so a
# rendered-but-empty secrets entry leaked the literal line into $TOKEN and
# defeated the [ -z ] guard (review 2026-06-10).
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

[ -n "$FORGE" ] || FORGE="$(yaml_lookup nos_agent_forge config.yml default.config.yml)"
[ -n "$FORGE" ] || FORGE="gitlab"
case "$FORGE" in gitlab|gitea) : ;; *) echo "[recipe-pr] unknown forge '$FORGE' (gitlab|gitea)"; exit 2 ;; esac

TENANT="$(yaml_lookup tenant_domain config.yml default.config.yml)"
if [ "$FORGE" = "gitlab" ]; then
  TOKEN="${GITLAB_TOKEN:-}"
  [ -n "$TOKEN" ] || TOKEN="$(yaml_lookup gitlab_api_token credentials.yml config.yml "$HOME/.nos/secrets.yml")"
  DOMAIN="${GITLAB_DOMAIN:-}"
  [ -n "$DOMAIN" ] || DOMAIN="$(yaml_lookup gitlab_domain credentials.yml config.yml)"
  [ -n "$DOMAIN" ] || { [ -n "$TENANT" ] && DOMAIN="gitlab.${TENANT}" || true; }
  OWNER="$(yaml_lookup gitlab_nos_repo_owner config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"
  [ -n "$OWNER" ] || OWNER="root"
  NAME="$(yaml_lookup gitlab_nos_repo_name config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"
  [ -n "$NAME" ] || NAME="nOS"
  # API via the LOCAL GitLab port, NOT the public domain: the Cloudflare edge
  # normalizes the URL-encoded slash in /projects/OWNER%2FNAME → the path
  # arrives as plain segments → GitLab 400s (live, 2026-06-10). This tool always
  # runs on the operator host, where GitLab listens on 127.0.0.1:<http_port>.
  # git push keeps the domain (no %2F in git URLs; proven by the trunk sync).
  GL_PORT="$(yaml_lookup gitlab_http_port config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"
  [ -n "$GL_PORT" ] || GL_PORT="8929"
  API_BASE="http://127.0.0.1:${GL_PORT}"
  MISSING_HINT="GITLAB_TOKEN/gitlab_api_token or gitlab_domain — is the forge provisioned? (gitlab_agent_forge=true + a run of the gitlab tag)"
else
  TOKEN="${GITEA_TOKEN:-}"
  [ -n "$TOKEN" ] || TOKEN="$(yaml_lookup gitea_api_token credentials.yml config.yml "$HOME/.nos/secrets.yml")"
  DOMAIN="${GITEA_DOMAIN:-}"
  [ -n "$DOMAIN" ] || DOMAIN="$(yaml_lookup gitea_domain credentials.yml config.yml)"
  [ -n "$DOMAIN" ] || { [ -n "$TENANT" ] && DOMAIN="git.${TENANT}" || true; }
  OWNER="$(yaml_lookup gitea_nos_repo_owner config.yml default.config.yml roles/pazny.gitea/defaults/main.yml)"
  [ -n "$OWNER" ] || OWNER="${USER:-$(whoami)}"
  NAME="$(yaml_lookup gitea_nos_repo_name config.yml default.config.yml roles/pazny.gitea/defaults/main.yml)"
  [ -n "$NAME" ] || NAME="nOS"
  MISSING_HINT="GITEA_TOKEN/gitea_api_token or gitea_domain — is the forge provisioned? (T32 #35)"
fi

if [ -z "$TOKEN" ] || [ -z "$DOMAIN" ]; then
  echo "[recipe-pr] missing ${MISSING_HINT}"
  exit 2
fi

# ── 3. Branch + commit + push to the forge + open the PR/MR (never merge) ─────
command -v git >/dev/null 2>&1 || { echo "[recipe-pr] git not found"; exit 2; }
if git diff --quiet -- "$RECIPE" && git diff --cached --quiet -- "$RECIPE"; then
  echo "[recipe-pr] $RECIPE has no pending changes — nothing to PR"; exit 0
fi

# Pre-flight: the BASE branch must EXIST on the forge. Pushing into an EMPTY
# project would make fix/recipe-* the default (protected) branch and the MR
# create would 4xx — run the trunk sync first (review 2026-06-10).
if [ "$FORGE" = "gitlab" ]; then
  BCHECK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    -H "PRIVATE-TOKEN: ${TOKEN}" \
    "${API_BASE}/api/v4/projects/${OWNER}%2F${NAME}/repository/branches/${BASE}" || echo "000")
else
  BCHECK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    -H "Authorization: token ${TOKEN}" \
    "https://${DOMAIN}/api/v1/repos/${OWNER}/${NAME}/branches/${BASE}" || echo "000")
fi
if [ "$BCHECK" != "200" ]; then
  echo "[recipe-pr] base branch '${BASE}' not found on ${FORGE} (HTTP ${BCHECK}) — push trunk first:"
  echo "             tools/sync-trunk-to-${FORGE}.sh"
  exit 2
fi

TS="$(date +%Y%m%d-%H%M%S)"
BRANCH="fix/recipe-${SERVICE}-${TS}"
PUSH_URL="https://oauth2:${TOKEN}@${DOMAIN}/${OWNER}/${NAME}.git"

# Cut the branch off BASE (not current HEAD — on pzny/a leading dev the MR would
# carry unrelated commits); carry the uncommitted recipe edit via stash.
ORIG_REF="$(git rev-parse --abbrev-ref HEAD)"
BASE_REF="$BASE"
git rev-parse --verify --quiet "refs/heads/${BASE}" >/dev/null || BASE_REF="$ORIG_REF"
echo "[recipe-pr] branch ${BRANCH} off ${BASE_REF}; push → ${FORGE} ${OWNER}/${NAME}"
git stash push -q -- "$RECIPE"
git switch -qc "$BRANCH" "$BASE_REF" || { git stash pop -q || true; echo "[recipe-pr] cannot branch off ${BASE_REF}"; exit 1; }
SWITCHED=1
git stash pop -q || { echo "[recipe-pr] stash pop conflict — recipe differs between ${ORIG_REF} and ${BASE_REF}; resolve manually (git stash list)"; exit 1; }
git add -- "$RECIPE"
git commit -q -m "feat(upgrade): ${SERVICE} recipe (agent-drafted)" -m "- validated: schema + from_regex + template-var-resolvable gates
- opened via tools/recipe-pr.sh; human review + merge gates the apply"
# Push the branch to the forge (output suppressed: git errors echo the URL,
# which embeds the token).
git push "$PUSH_URL" "$BRANCH" >/dev/null 2>&1 \
  || { echo "[recipe-pr] git push to ${FORGE} failed (is the repo writable + trunk synced? see T32)"; exit 1; }

TITLE="feat(upgrade): ${SERVICE} recipe (agent-drafted)"
DESC="Agent-drafted upgrade recipe for **${SERVICE}**, validated through the recipe gates (schema + from_regex + template-var-resolvable). Review + merge here gates the apply; promotion to GitHub is a separate operator step (tools/promote-public.sh)."

# Failed create exits 1 (review 2026-06-10: a silent exit-0 left the commit on a
# pushed branch with NO MR, and the re-run dead-ended on "no pending changes").
RC=0
if [ "$FORGE" = "gitlab" ]; then
  API="${API_BASE}/api/v4/projects/${OWNER}%2F${NAME}/merge_requests"
  BODY=$(printf '{"source_branch":"%s","target_branch":"%s","title":"%s","description":"%s","remove_source_branch":true}' \
    "$BRANCH" "$BASE" "$TITLE" "$DESC")
  HTTP=$(curl -s -o /tmp/recipe-pr-resp.$$ -w '%{http_code}' \
    -X POST -H "PRIVATE-TOKEN: ${TOKEN}" -H "Content-Type: application/json" \
    --max-time 10 -d "$BODY" "$API" || echo "000")
  case "$HTTP" in
    201) echo "[recipe-pr] GitLab MR opened: $(grep -o '"web_url":"[^"]*merge_requests[^"]*"' /tmp/recipe-pr-resp.$$ | head -1 | cut -d'"' -f4)" ;;
    409) echo "[recipe-pr] a GitLab MR for ${BRANCH}→${BASE} already exists" ;;
    000) echo "[recipe-pr] GitLab unreachable at ${DOMAIN} — branch ${BRANCH} IS pushed; open the MR manually"; RC=1 ;;
    *)   echo "[recipe-pr] GitLab MR create returned HTTP ${HTTP} — branch ${BRANCH} IS pushed; fix the cause and open the MR manually:"; cat /tmp/recipe-pr-resp.$$; RC=1 ;;
  esac
else
  API="https://${DOMAIN}/api/v1/repos/${OWNER}/${NAME}/pulls"
  BODY=$(printf '{"head":"%s","base":"%s","title":"%s","body":"%s"}' \
    "$BRANCH" "$BASE" "$TITLE" "$DESC")
  HTTP=$(curl -s -o /tmp/recipe-pr-resp.$$ -w '%{http_code}' \
    -X POST -H "Authorization: token ${TOKEN}" -H "Content-Type: application/json" \
    --max-time 10 -d "$BODY" "$API" || echo "000")
  case "$HTTP" in
    201) echo "[recipe-pr] Gitea PR opened: $(grep -o '"html_url":"[^"]*"' /tmp/recipe-pr-resp.$$ | head -1 | cut -d'"' -f4)" ;;
    409) echo "[recipe-pr] a Gitea PR for ${BRANCH}→${BASE} already exists" ;;
    000) echo "[recipe-pr] Gitea unreachable at ${DOMAIN} — branch ${BRANCH} IS pushed; open the PR manually"; RC=1 ;;
    *)   echo "[recipe-pr] Gitea PR create returned HTTP ${HTTP} — branch ${BRANCH} IS pushed; fix the cause and open the PR manually:"; cat /tmp/recipe-pr-resp.$$; RC=1 ;;
  esac
fi
rm -f /tmp/recipe-pr-resp.$$
exit "$RC"
