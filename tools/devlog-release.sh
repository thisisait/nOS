#!/usr/bin/env bash
# =============================================================================
# devlog-release.sh — mechanical pre-flight for a release cut.
#
# The narrative half (2nd-level review, docs consolidation, release blog
# entry) is the /devlog skill's `release` mode; this script verifies the
# artifacts it should have produced, then prints the remaining checklist.
# Deliberately does NOT run tools/ci-local.sh (separate gate, separate
# failure domain) and does NOT push/tag anything itself.
#
# Usage: tools/devlog-release.sh v0.7-beta
# Exit:  0 = all pre-flight checks green
#        1 = a check failed (message names it)
#        2 = usage error
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-}"
[[ -n "$VERSION" ]] || { echo "usage: tools/devlog-release.sh vX.Y-beta" >&2; exit 2; }
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+ ]] || { echo "version must look like vX.Y[-suffix]" >&2; exit 2; }

cd "$REPO"
fail() { echo "PRE-FLIGHT FAIL: $*" >&2; exit 1; }

echo "── devlog release pre-flight ($VERSION) ──────────────────────────"

# 1. Working tree clean (the release commit must already be authored).
[[ -z "$(git status --porcelain)" ]] \
  || fail "git working tree not clean — commit or stash first"
echo "ok: git tree clean"

# 2. Bundle freshness (entries ↔ committed bundle byte-parity).
python3 tools/devlog-compile.py --check \
  || fail "devlog bundle stale — run tools/devlog-compile.py and commit"

# 3. A release entry for this version exists in the devlog.
grep -l "release: $VERSION" docs/devlog/nos-core/*/*.md >/dev/null 2>&1 \
  || fail "no devlog entry with 'release: $VERSION' — /devlog release authors it"
echo "ok: release entry present ($(grep -l "release: $VERSION" docs/devlog/nos-core/*/*.md | tr '\n' ' '))"

# 4. RELEASE.md carries the matching section.
grep -q "^## $VERSION" RELEASE.md \
  || fail "RELEASE.md has no '## $VERSION' section"
echo "ok: RELEASE.md section present"

# 5. active-work.md within the pointer ceiling (mirrors the pytest gate).
lines=$(wc -l < docs/active-work.md | tr -d ' ')
[[ "$lines" -le 150 ]] \
  || fail "docs/active-work.md is $lines lines (>150) — move narrative to the devlog"
echo "ok: active-work.md $lines lines"

# 6. Tag must not already exist.
git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null \
  && fail "tag $VERSION already exists" || true
echo "ok: tag $VERSION free"

cat <<EOF

ALL PRE-FLIGHT CHECKS GREEN. Remaining release checklist (operator-gated):

  1. tools/ci-local.sh                 # frozen 1:1 wet-test gate
  2. git push origin dev
  3. gh pr create --base master --head dev ...
  4. (wait for green Integration ubuntu-24.04 on the PR)
  5. gh pr merge <N> --rebase --admin  # sole-operator admin bypass
  6. git checkout dev && git fetch && git reset --hard origin/master
     git push --force-with-lease origin dev
  7. git tag $VERSION master && git push origin $VERSION
     # ↑ the tag push triggers .github/workflows/pages.yml → devlog publish
  8. gh release create $VERSION --notes-file <(...)
  9. next playbook run (or --tags devlog) syncs new entries into WordPress
EOF
