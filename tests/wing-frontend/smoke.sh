#!/usr/bin/env bash
# Glasswing frontend smoke test
#
# Headless, dependency-free check that the state-framework views render with:
#   - expected HTML skeleton
#   - their CSS + JS assets loaded
#   - no obvious Latte render errors
#
# Usage:
#   BASE_URL=https://glasswing.dev.local ./tests/glasswing-frontend/smoke.sh
#
# Exits non-zero on the first failure. This is a best-effort check; full
# coverage lives in presenter-level PHPUnit tests (agent 7).

set -u
BASE_URL="${BASE_URL:-http://localhost:8080}"
CURL_OPTS=(${CURL_OPTS:--fsSL --max-time 10 --insecure})
FAILED=0

say() { printf '  %s\n' "$*"; }
ok()  { printf '  \033[32mOK\033[0m  %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAILED=$((FAILED + 1)); }

check_path() {
    local path="$1" ; shift
    local label="$1" ; shift
    local body
    body=$(curl "${CURL_OPTS[@]}" "$BASE_URL$path" 2>/dev/null) || { bad "$label — HTTP fetch failed ($BASE_URL$path)"; return; }

    # Must not contain a raw Latte error marker
    if echo "$body" | grep -qiE 'fatal error|latte.*error|uncaught'; then
        bad "$label — page contains a render error"
        return
    fi

    # Must carry the outer @layout.latte shell
    if ! echo "$body" | grep -q '<div class="header">'; then
        bad "$label — missing layout (@layout.latte not applied)"
        return
    fi

    # Must load at least one asset
    for needle in "$@"; do
        if ! echo "$body" | grep -q "$needle"; then
            bad "$label — missing expected needle: $needle"
            return
        fi
    done
    ok "$label"
}

printf 'Glasswing frontend smoke — BASE_URL=%s\n' "$BASE_URL"

check_path "/migrations"              "Migrations index"  "migrations.css"  "migrations.js"  "mig-grid"
check_path "/upgrades"                "Upgrades matrix"   "upgrades.css"    "upg-matrix"
check_path "/timeline"                "Timeline"          "timeline.css"    "tl-filters"     "widget-timeline.js"
check_path "/coexistence"             "Coexistence"       "coexistence.css" "widget-cutover-confirm.js"

# Static assets should be reachable too
for asset in migrations.css upgrades.css timeline.css coexistence.css widgets.css \
             migrations.js widget-version-health.js widget-timeline.js widget-cutover-confirm.js ; do
    if curl "${CURL_OPTS[@]}" -o /dev/null "$BASE_URL/assets/$asset" 2>/dev/null; then
        ok "asset /assets/$asset"
    else
        bad "asset /assets/$asset — not fetchable"
    fi
done

printf '\n'
if [ "$FAILED" -gt 0 ]; then
    printf '\033[31m%d check(s) failed\033[0m\n' "$FAILED"
    exit 1
fi
printf '\033[32mAll smoke checks passed\033[0m\n'
