#!/usr/bin/env bash
# tools/recipe-pr.sh — validate an upgrade recipe and (optionally) open a PR on
# the LOCAL Gitea (never GitHub). The agent-authoring safety boundary:
# upgrade-architect drafts a recipe into upgrades/<service>.yml; this validates
# it through the authoritative gates and, with --open-pr, branches + commits +
# pushes to GITEA and opens a Gitea PR for a human to review + merge. It NEVER
# merges and NEVER force-pushes. The public GitHub PR is a SEPARATE, operator-run
# step (tools/promote-public.sh) — the agent loop stays off the public internet.
#
# DRY-RUN BY DEFAULT (operator doctrine: dry-run default + explicit confirm):
#   tools/recipe-pr.sh <service>             # validate only — no git, no push
#   tools/recipe-pr.sh <service> --open-pr   # validate, then branch+commit+push+Gitea-PR
#   tools/recipe-pr.sh <service> --open-pr --base master   # base branch (default: dev)
#
# Gitea config is auto-discovered (same pattern as tools/nos-push):
#   * token  — GITEA_TOKEN env, else gitea_api_token in credentials.yml /
#              config.yml / ~/.nos/secrets.yml (provisioned by the playbook)
#   * domain — GITEA_DOMAIN env, else gitea_domain in credentials/config,
#              else git.<tenant_domain>
#   * owner  — gitea_nos_repo_owner (default: $USER)
#   * name   — gitea_nos_repo_name  (default: nOS)
#
# DEPENDS ON T32 #35: the Gitea nOS repo must be a WRITABLE working repo, not
# the current A16 pull-mirror (Gitea rejects pushes to mirror repos). The
# validate-only path works today; --open-pr needs the writable repo.
#
# `set -eu` only — NO pipefail (same as tools/nos-push): the grep|sed|head
# config-parse chains legitimately return 1 on no-match, which pipefail would
# propagate and abort under set -e. The explicit fallbacks handle missing values.
set -eu

# Clean up the curl response temp file on ANY exit path. `set -eu` aborts the
# script if `cat`/the case arm exits non-zero between the curl write (l.125) and
# the explicit rm (l.134), orphaning /tmp/recipe-pr-resp.$$; the trap guarantees
# removal. $$ is fixed at parse time, so the path matches the one curl writes.
trap 'rm -f "/tmp/recipe-pr-resp.$$"' EXIT INT TERM

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SERVICE=""
OPEN_PR=0
BASE="dev"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --open-pr) OPEN_PR=1 ;;
    --base) shift; BASE="${1:-dev}" ;;
    -*) echo "[recipe-pr] unknown flag: $1"; exit 2 ;;
    *) SERVICE="$1" ;;
  esac
  shift
done
[ -n "$SERVICE" ] || { echo "usage: tools/recipe-pr.sh <service> [--open-pr] [--base <branch>]"; exit 2; }

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
  echo "[recipe-pr] validate-only (pass --open-pr to branch+commit+push+Gitea-PR)"
  exit 0
fi

# ── 2. Gitea config discovery (mirrors tools/nos-push) ────────────────────────
# yaml_lookup <key> <file>... — first plain-scalar value, skipping {{ jinja }}.
yaml_lookup() {
  local key="$1"; shift; local v
  for f in "$@"; do
    [ -f "$f" ] || continue
    v=$(grep -h -E "^${key}:" "$f" 2>/dev/null \
        | sed -E 's/^[^:]+:[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/' \
        | grep -vE '\{\{' | head -1 || true)
    [ -n "${v:-}" ] && { printf '%s' "$v"; return 0; }
  done
  return 0
}

TOKEN="${GITEA_TOKEN:-}"
[ -n "$TOKEN" ] || TOKEN="$(yaml_lookup gitea_api_token credentials.yml config.yml "$HOME/.nos/secrets.yml")"
DOMAIN="${GITEA_DOMAIN:-}"
[ -n "$DOMAIN" ] || DOMAIN="$(yaml_lookup gitea_domain credentials.yml config.yml)"
if [ -z "$DOMAIN" ]; then
  TENANT="$(yaml_lookup tenant_domain config.yml default.config.yml)"
  [ -n "$TENANT" ] && DOMAIN="git.${TENANT}"
fi
OWNER="$(yaml_lookup gitea_nos_repo_owner config.yml default.config.yml roles/pazny.gitea/defaults/main.yml)"
[ -n "$OWNER" ] || OWNER="${USER:-$(whoami)}"
NAME="$(yaml_lookup gitea_nos_repo_name config.yml default.config.yml roles/pazny.gitea/defaults/main.yml)"
[ -n "$NAME" ] || NAME="nOS"

if [ -z "$TOKEN" ] || [ -z "$DOMAIN" ]; then
  echo "[recipe-pr] missing GITEA_TOKEN/gitea_api_token or gitea_domain — cannot open a Gitea PR"
  exit 2
fi

# ── 3. Branch + commit + push to GITEA + open a Gitea PR (never merge) ─────────
command -v git >/dev/null 2>&1 || { echo "[recipe-pr] git not found"; exit 2; }
if git diff --quiet -- "$RECIPE" && git diff --cached --quiet -- "$RECIPE"; then
  echo "[recipe-pr] $RECIPE has no pending changes — nothing to PR"; exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
BRANCH="fix/recipe-${SERVICE}-${TS}"
GITEA_PUSH_URL="https://oauth2:${TOKEN}@${DOMAIN}/${OWNER}/${NAME}.git"

echo "[recipe-pr] branch ${BRANCH} off ${BASE}; push → Gitea ${OWNER}/${NAME}"
git switch -c "$BRANCH"
git add -- "$RECIPE"
git commit -q -m "feat(upgrade): ${SERVICE} recipe (agent-drafted)" -m "- validated: schema + from_regex + template-var-resolvable gates
- opened via tools/recipe-pr.sh; human review + merge gates the apply"
# Push the branch to Gitea (token in URL, never echoed).
git push "$GITEA_PUSH_URL" "$BRANCH" >/dev/null 2>&1 \
  || { echo "[recipe-pr] git push to Gitea failed (is the repo writable? see T32 #35)"; exit 1; }

API="https://${DOMAIN}/api/v1/repos/${OWNER}/${NAME}/pulls"
BODY=$(printf '{"head":"%s","base":"%s","title":"feat(upgrade): %s recipe (agent-drafted)","body":"Agent-drafted upgrade recipe for **%s**, validated through the recipe gates (schema + from_regex + template-var-resolvable). Review + merge here gates the apply; promotion to GitHub is a separate operator step (tools/promote-public.sh)."}' \
  "$BRANCH" "$BASE" "$SERVICE" "$SERVICE")
HTTP=$(curl -s -o /tmp/recipe-pr-resp.$$ -w '%{http_code}' \
  -X POST -H "Authorization: token ${TOKEN}" -H "Content-Type: application/json" \
  --max-time 10 -d "$BODY" "$API" || echo "000")
case "$HTTP" in
  201) echo "[recipe-pr] Gitea PR opened: $(grep -o '"html_url":"[^"]*"' /tmp/recipe-pr-resp.$$ | head -1 | cut -d'"' -f4)" ;;
  409) echo "[recipe-pr] a Gitea PR for ${BRANCH}→${BASE} already exists" ;;
  000) echo "[recipe-pr] Gitea unreachable at ${DOMAIN} — branch pushed, open the PR manually" ;;
  *)   echo "[recipe-pr] Gitea PR create returned HTTP ${HTTP}:"; cat /tmp/recipe-pr-resp.$$ ;;
esac
rm -f /tmp/recipe-pr-resp.$$
