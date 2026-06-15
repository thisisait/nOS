#!/usr/bin/env bash
# tools/migration-pr.sh — validate an authored migration record + its version
# bump and (optionally) open a PR/MR on the LOCAL forge (never GitHub). The
# generalized sibling of tools/recipe-pr.sh: where recipe-pr.sh stages a single
# upgrades/<service>.yml, this stages the migration ARTIFACT SET —
# files/anatomy/migrations/<migration-id>.yml AND default.config.yml (the
# <service>_version bump). The two MUST travel together: a version bump without
# the migration record (or vice-versa) ships a half-migration; a bump-less
# migration reverts on the next normal main.yml render (upgrades/README.md).
#
# The agent-authoring safety boundary: migration-author writes the migration
# record + bumps the version; this validates them through the authoritative
# migration gates and, with --open-pr, branches + commits + pushes to the local
# forge and opens a review request (GATE 2) for a human to review + merge. It
# NEVER merges and NEVER force-pushes. The public GitHub PR is a SEPARATE,
# operator-run step (tools/promote-public.sh) — the agent loop stays off the
# public internet.
#
# FORGE TARGET (T32.2): default comes from `nos_agent_forge` in config.yml /
# default.config.yml (repo default: "gitlab"). Override per-run with
# --forge gitea|gitlab.
#
# DRY-RUN BY DEFAULT (operator doctrine: dry-run default + explicit confirm):
#   tools/migration-pr.sh <service> <migration-id>             # validate only
#   tools/migration-pr.sh <service> <migration-id> --open-pr   # +branch+commit+push+MR
#   tools/migration-pr.sh <service> <migration-id> --open-pr --base master
#   tools/migration-pr.sh <service> <migration-id> --open-pr --forge gitea
#
# GATE 2 — forge merge → review_status='merged' (PULL model, B6). AFTER the
# operator merges the local-forge MR, this flips the migrations_authored row to
# merged + stamps committed_sha + emits migration_promoted (via the Wing bridge
# bin/promote-migration.php). It is the ONLY path to 'merged' (Wing's
# setReviewStatus() hard-refuses it). §7-Q1 is answered PULL (no inbound forge
# webhook into Bone); this CLI flip + the next-deploy ingest pass are the two
# pull entry points. When --committed-sha is omitted the merge commit SHA is
# read from the merged MR on the local forge (the --open-pr discovery chain).
#   tools/migration-pr.sh <service> <migration-id> --mark-merged
#   tools/migration-pr.sh <service> <migration-id> --mark-merged --committed-sha <sha>
#   tools/migration-pr.sh <service> <migration-id> --mark-merged --uuid <authoring-uuid>
#
# Forge config auto-discovery is identical to tools/recipe-pr.sh (token/domain/
# owner/name lookup chain, the 127.0.0.1:<http_port> %2F-dodge for the GitLab
# API, the base-branch preflight, the oauth2:<token>@<domain> push URL). The
# validate-only path works with no forge at all.
#
# `set -eu` only — NO pipefail (same as recipe-pr.sh / nos-push): the grep|sed|
# head config-parse chains legitimately return 1 on no-match.
set -eu

SWITCHED=0
ORIG_REF=""
cleanup() {
  rm -f "/tmp/migration-pr-resp.$$"
  if [ "${SWITCHED:-0}" = 1 ] && [ -n "${ORIG_REF:-}" ]; then
    git switch -q "$ORIG_REF" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SERVICE=""
MIGRATION_ID=""
OPEN_PR=0
MARK_MERGED=0
COMMITTED_SHA=""
AUTHORING_UUID=""
BASE="dev"
FORGE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --open-pr) OPEN_PR=1 ;;
    --mark-merged) MARK_MERGED=1 ;;
    --committed-sha) shift; COMMITTED_SHA="${1:-}" ;;
    --uuid) shift; AUTHORING_UUID="${1:-}" ;;
    --base) shift; BASE="${1:-dev}" ;;
    --forge) shift; FORGE="${1:-}" ;;
    -*) echo "[migration-pr] unknown flag: $1"; exit 2 ;;
    *)
      if [ -z "$SERVICE" ]; then SERVICE="$1"
      elif [ -z "$MIGRATION_ID" ]; then MIGRATION_ID="$1"
      else echo "[migration-pr] unexpected positional: $1"; exit 2; fi
      ;;
  esac
  shift
done
if [ -z "$SERVICE" ] || [ -z "$MIGRATION_ID" ]; then
  echo "usage: tools/migration-pr.sh <service> <migration-id> [--open-pr | --mark-merged] [--base <branch>] [--forge gitlab|gitea]"
  exit 2
fi
if [ "$OPEN_PR" = 1 ] && [ "$MARK_MERGED" = 1 ]; then
  echo "[migration-pr] --open-pr and --mark-merged are mutually exclusive (open the MR, THEN merge it on the forge, THEN --mark-merged)"
  exit 2
fi

# Accept either the bare id or a path; normalize to the id (filename sans .yml).
MIGRATION_ID="$(basename "$MIGRATION_ID")"
MIGRATION_ID="${MIGRATION_ID%.yml}"
MIGRATION="files/anatomy/migrations/${MIGRATION_ID}.yml"

# yaml_lookup — config value reader shared by the forge-discovery (--open-pr)
# AND the merge SHA discovery (--mark-merged). Mirrors tools/recipe-pr.sh /
# tools/nos-push: grep|sed|head, {{ Jinja }} placeholders skipped. (set -eu only,
# NO pipefail — the grep|sed|head chain legitimately returns 1 on no-match.)
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

[ -f "$MIGRATION" ] || { echo "[migration-pr] no migration record at $MIGRATION"; exit 2; }

# ── GATE 2 — forge merge → review_status='merged' (B6, PULL model) ────────────
# AFTER the operator merges the local-forge MR, flip the migrations_authored row
# to merged + stamp committed_sha + emit migration_promoted, via the Wing bridge
# bin/promote-migration.php (the ONLY writer of 'merged'; Wing's setReviewStatus
# refuses it). Resolves the merge commit SHA from --committed-sha, else reads it
# off the merged MR on the local forge. This path is independent of the
# validate→open-pr flow (no pending changes required — the merge already
# happened on the forge).
if [ "$MARK_MERGED" = 1 ]; then
  # Locate the Wing bridge: prefer the deployed install (~/wing/app/bin), fall
  # back to the in-repo source so an operator can run it pre-deploy.
  WING_BIN=""
  for cand in "${HOME}/wing/app/bin/promote-migration.php" \
              "${REPO_ROOT}/files/anatomy/wing/bin/promote-migration.php"; do
    [ -f "$cand" ] && { WING_BIN="$cand"; break; }
  done
  [ -n "$WING_BIN" ] || { echo "[migration-pr] promote-migration.php bridge not found (deploy Wing or run from the repo)"; exit 2; }
  command -v php >/dev/null 2>&1 || { echo "[migration-pr] php not found — the merge-flip bridge needs the Wing PHP runtime"; exit 2; }

  WING_DATA_DIR="${WING_DATA_DIR:-${HOME}/wing/app/data}"
  [ -f "${WING_DATA_DIR}/wing.db" ] || { echo "[migration-pr] wing.db not found at ${WING_DATA_DIR} (is Wing provisioned?)"; exit 2; }

  # If the SHA wasn't supplied, read the merge commit off the MR on the local
  # forge. Reuses the same %2F-dodge local-port API the --open-pr path uses; a
  # merged MR carries the squash/merge commit in merge_commit_sha (GitLab) /
  # merge_commit_sha (Gitea). We never reach the public domain (token-bearing).
  if [ -z "$COMMITTED_SHA" ]; then
    [ -n "$FORGE" ] || FORGE="$(yaml_lookup nos_agent_forge config.yml default.config.yml)"
    [ -n "$FORGE" ] || FORGE="gitlab"
    TENANT="$(yaml_lookup tenant_domain config.yml default.config.yml)"
    if [ "$FORGE" = "gitlab" ]; then
      TOKEN="${GITLAB_TOKEN:-}"
      [ -n "$TOKEN" ] || TOKEN="$(yaml_lookup gitlab_api_token credentials.yml config.yml "$HOME/.nos/secrets.yml")"
      OWNER="$(yaml_lookup gitlab_nos_repo_owner config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"; [ -n "$OWNER" ] || OWNER="root"
      NAME="$(yaml_lookup gitlab_nos_repo_name config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"; [ -n "$NAME" ] || NAME="nOS"
      GL_PORT="$(yaml_lookup gitlab_http_port config.yml default.config.yml roles/pazny.gitlab/defaults/main.yml)"; [ -n "$GL_PORT" ] || GL_PORT="8929"
      if [ -n "$TOKEN" ]; then
        # Newest merged MR whose source branch is this migration's fix branch.
        SRC=$(curl -s --max-time 10 -H "PRIVATE-TOKEN: ${TOKEN}" \
          "http://127.0.0.1:${GL_PORT}/api/v4/projects/${OWNER}%2F${NAME}/merge_requests?state=merged&source_branch=fix/migration-${SERVICE}&order_by=updated_at&per_page=1" 2>/dev/null || true)
        COMMITTED_SHA=$(printf '%s' "$SRC" | grep -o '"merge_commit_sha":"[0-9a-f]*"' | head -1 | cut -d'"' -f4 || true)
        [ -n "$COMMITTED_SHA" ] || COMMITTED_SHA=$(printf '%s' "$SRC" | grep -o '"sha":"[0-9a-f]*"' | head -1 | cut -d'"' -f4 || true)
      fi
    else
      TOKEN="${GITEA_TOKEN:-}"
      [ -n "$TOKEN" ] || TOKEN="$(yaml_lookup gitea_api_token credentials.yml config.yml "$HOME/.nos/secrets.yml")"
      DOMAIN="${GITEA_DOMAIN:-}"; [ -n "$DOMAIN" ] || DOMAIN="$(yaml_lookup gitea_domain credentials.yml config.yml)"
      [ -n "$DOMAIN" ] || { [ -n "$TENANT" ] && DOMAIN="git.${TENANT}" || true; }
      OWNER="$(yaml_lookup gitea_nos_repo_owner config.yml default.config.yml roles/pazny.gitea/defaults/main.yml)"; [ -n "$OWNER" ] || OWNER="${USER:-$(whoami)}"
      NAME="$(yaml_lookup gitea_nos_repo_name config.yml default.config.yml roles/pazny.gitea/defaults/main.yml)"; [ -n "$NAME" ] || NAME="nOS"
      if [ -n "$TOKEN" ] && [ -n "$DOMAIN" ]; then
        SRC=$(curl -s --max-time 10 -H "Authorization: token ${TOKEN}" \
          "https://${DOMAIN}/api/v1/repos/${OWNER}/${NAME}/pulls?state=closed&limit=20" 2>/dev/null || true)
        COMMITTED_SHA=$(printf '%s' "$SRC" | grep -o '"merge_commit_sha":"[0-9a-f]*"' | head -1 | cut -d'"' -f4 || true)
      fi
    fi
  fi
  if [ -z "$COMMITTED_SHA" ]; then
    echo "[migration-pr] could not resolve the merge commit SHA — pass --committed-sha <sha> (the operator merge commit on the local forge)"
    exit 2
  fi

  echo "[migration-pr] GATE 2 flip: ${SERVICE} ${MIGRATION_ID} → merged @ ${COMMITTED_SHA}"
  BRIDGE_ARGS=(--mark-merged --committed-sha "$COMMITTED_SHA" --data-dir "$WING_DATA_DIR" --actor operator)
  if [ -n "$AUTHORING_UUID" ]; then
    BRIDGE_ARGS+=(--uuid "$AUTHORING_UUID")
  else
    BRIDGE_ARGS+=(--migration-id "$MIGRATION_ID")
  fi
  php "$WING_BIN" "${BRIDGE_ARGS[@]}"
  exit $?
fi

# The artifact SET this PR stages — the migration record AND the version-bump
# in default.config.yml. (recipe-pr.sh stages only the single recipe.)
CONFIG_FILE="default.config.yml"
STAGE_FILES=("$MIGRATION" "$CONFIG_FILE")

# ── 1. Validate through the authoritative migration gates ─────────────────────
echo "[migration-pr] validating $MIGRATION"
if command -v yamllint >/dev/null 2>&1; then
  if yamllint -f parsable "$MIGRATION" | grep -qE ':[0-9]+:[0-9]+: \[error\]'; then
    echo "[migration-pr] yamllint errors in $MIGRATION"; exit 1
  fi
fi
python3 -m pytest -q tests/migrations/ \
  || { echo "[migration-pr] migration gates FAILED — fix before opening a PR"; exit 1; }
echo "[migration-pr] OK — $MIGRATION passes schema + idempotency + template-var gates"

if [ "$OPEN_PR" != 1 ]; then
  echo "[migration-pr] validate-only (pass --open-pr to branch+commit+push+open the review request)"
  exit 0
fi

# ── 2. Forge config discovery (mirrors tools/recipe-pr.sh / tools/nos-push) ───
[ -n "$FORGE" ] || FORGE="$(yaml_lookup nos_agent_forge config.yml default.config.yml)"
[ -n "$FORGE" ] || FORGE="gitlab"
case "$FORGE" in gitlab|gitea) : ;; *) echo "[migration-pr] unknown forge '$FORGE' (gitlab|gitea)"; exit 2 ;; esac

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
  # API via the LOCAL GitLab port, NOT the public domain (Cloudflare edge
  # normalizes the URL-encoded slash in /projects/OWNER%2FNAME → 400). git push
  # keeps the domain (no %2F in git URLs).
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
  echo "[migration-pr] missing ${MISSING_HINT}"
  exit 2
fi

# ── 3. Branch + commit + push to the forge + open the PR/MR (never merge) ─────
command -v git >/dev/null 2>&1 || { echo "[migration-pr] git not found"; exit 2; }
# Something in the artifact set must have pending changes.
HAS_PENDING=0
for f in "${STAGE_FILES[@]}"; do
  if ! { git diff --quiet -- "$f" && git diff --cached --quiet -- "$f"; }; then
    HAS_PENDING=1
  fi
done
if [ "$HAS_PENDING" != 1 ]; then
  echo "[migration-pr] migration artifact set has no pending changes — nothing to PR"; exit 0
fi

# Pre-flight: the BASE branch must EXIST on the forge (else fix/migration-*
# would become the default protected branch + the MR create 4xx).
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
  echo "[migration-pr] base branch '${BASE}' not found on ${FORGE} (HTTP ${BCHECK}) — push trunk first:"
  echo "             tools/sync-trunk-to-${FORGE}.sh"
  exit 2
fi

TS="$(date +%Y%m%d-%H%M%S)"
BRANCH="fix/migration-${SERVICE}-${TS}"
PUSH_URL="https://oauth2:${TOKEN}@${DOMAIN}/${OWNER}/${NAME}.git"

# Cut the branch off BASE (not current HEAD); carry the uncommitted edits via
# stash so the MR is clean on top of BASE.
ORIG_REF="$(git rev-parse --abbrev-ref HEAD)"
BASE_REF="$BASE"
git rev-parse --verify --quiet "refs/heads/${BASE}" >/dev/null || BASE_REF="$ORIG_REF"
echo "[migration-pr] branch ${BRANCH} off ${BASE_REF}; push → ${FORGE} ${OWNER}/${NAME}"
git stash push -q -- "${STAGE_FILES[@]}"
git switch -qc "$BRANCH" "$BASE_REF" || { git stash pop -q || true; echo "[migration-pr] cannot branch off ${BASE_REF}"; exit 1; }
SWITCHED=1
git stash pop -q || { echo "[migration-pr] stash pop conflict — artifacts differ between ${ORIG_REF} and ${BASE_REF}; resolve manually (git stash list)"; exit 1; }
git add -- "${STAGE_FILES[@]}"
git commit -q -m "feat(migration): ${SERVICE} ${MIGRATION_ID} (agent-authored)" -m "- migration record + default.config.yml version bump (the artifact set)
- validated: schema + idempotency + template-var-resolvable gates
- opened via tools/migration-pr.sh; human review + merge gates the apply (GATE 2)"
# Push (output suppressed: git errors echo the URL, which embeds the token).
git push "$PUSH_URL" "$BRANCH" >/dev/null 2>&1 \
  || { echo "[migration-pr] git push to ${FORGE} failed (is the repo writable + trunk synced? see T32)"; exit 1; }

TITLE="feat(migration): ${SERVICE} ${MIGRATION_ID} (agent-authored)"
DESC="Agent-authored migration record for **${SERVICE}** (\`${MIGRATION_ID}\`) + the matching \`${SERVICE}_version\` bump in default.config.yml, validated through the migration gates (schema + idempotency + template-var-resolvable). The record + the version bump travel together — a bump-less migration reverts on the next normal run. Review + merge here gates the apply (GATE 2); promotion to GitHub is a separate operator step (tools/promote-public.sh)."

# Failed create exits 1 (a silent exit-0 would leave the commit on a pushed
# branch with NO MR, and the re-run would dead-end on "no pending changes").
RC=0
if [ "$FORGE" = "gitlab" ]; then
  API="${API_BASE}/api/v4/projects/${OWNER}%2F${NAME}/merge_requests"
  BODY=$(printf '{"source_branch":"%s","target_branch":"%s","title":"%s","description":"%s","remove_source_branch":true}' \
    "$BRANCH" "$BASE" "$TITLE" "$DESC")
  HTTP=$(curl -s -o /tmp/migration-pr-resp.$$ -w '%{http_code}' \
    -X POST -H "PRIVATE-TOKEN: ${TOKEN}" -H "Content-Type: application/json" \
    --max-time 10 -d "$BODY" "$API" || echo "000")
  case "$HTTP" in
    201) echo "[migration-pr] GitLab MR opened: $(grep -o '"web_url":"[^"]*merge_requests[^"]*"' /tmp/migration-pr-resp.$$ | head -1 | cut -d'"' -f4)" ;;
    409) echo "[migration-pr] a GitLab MR for ${BRANCH}→${BASE} already exists" ;;
    000) echo "[migration-pr] GitLab unreachable at ${DOMAIN} — branch ${BRANCH} IS pushed; open the MR manually"; RC=1 ;;
    *)   echo "[migration-pr] GitLab MR create returned HTTP ${HTTP} — branch ${BRANCH} IS pushed; fix the cause and open the MR manually:"; cat /tmp/migration-pr-resp.$$; RC=1 ;;
  esac
else
  API="https://${DOMAIN}/api/v1/repos/${OWNER}/${NAME}/pulls"
  BODY=$(printf '{"head":"%s","base":"%s","title":"%s","body":"%s"}' \
    "$BRANCH" "$BASE" "$TITLE" "$DESC")
  HTTP=$(curl -s -o /tmp/migration-pr-resp.$$ -w '%{http_code}' \
    -X POST -H "Authorization: token ${TOKEN}" -H "Content-Type: application/json" \
    --max-time 10 -d "$BODY" "$API" || echo "000")
  case "$HTTP" in
    201) echo "[migration-pr] Gitea PR opened: $(grep -o '"html_url":"[^"]*"' /tmp/migration-pr-resp.$$ | head -1 | cut -d'"' -f4)" ;;
    409) echo "[migration-pr] a Gitea PR for ${BRANCH}→${BASE} already exists" ;;
    000) echo "[migration-pr] Gitea unreachable at ${DOMAIN} — branch ${BRANCH} IS pushed; open the PR manually"; RC=1 ;;
    *)   echo "[migration-pr] Gitea PR create returned HTTP ${HTTP} — branch ${BRANCH} IS pushed; fix the cause and open the PR manually:"; cat /tmp/migration-pr-resp.$$; RC=1 ;;
  esac
fi
rm -f /tmp/migration-pr-resp.$$
exit "$RC"
