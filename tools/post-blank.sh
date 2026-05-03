#!/usr/bin/env bash
# tools/post-blank.sh — operator-facing post-blank verification runner.
#
# Single entry-point for "the blank just finished, what state are we in?"
# Sequences three checks the operator (or a Cowork session) walks every
# time, then prints the Wing UI deep-links so the human can eyeball the
# recent run.
#
# Steps:
#   1. NOS_WET=1 pytest tests/wet      → deterministic SQLite/JSONL/YAML
#   2. tools/nos-smoke.py              → HTTP probe of every service
#   3. echo Wing UI URLs               → /timeline /hub /gdpr /migrations
#
# Each step is gated so a failure in step N still surfaces step N+1's
# information (we want to see the Wing URLs even if pytest red-lines).
# Final exit code is the OR of step 1 + step 2; step 3 is informational.
#
# Env knobs:
#   NOS_HOST         tenant_domain (default: dev.local)
#   NOS_WET_STRICT   set to 0 to make missing artefacts SKIP instead of
#                    FAIL (default: 1, the strict post-blank stance)
#   NOS_TIER         smoke tier filter: '1', '2', or 'all' (default: all)
#   POST_BLANK_OPEN  set to 1 to auto-`open` Wing /timeline at the end
#
# Run:
#   bash tools/post-blank.sh
#   NOS_HOST=pazny.eu bash tools/post-blank.sh
#   POST_BLANK_OPEN=1 bash tools/post-blank.sh

set -uo pipefail   # NB: no `-e` — we WANT to keep going after step failures

# ── Resolve repo root regardless of cwd ───────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

NOS_HOST="${NOS_HOST:-dev.local}"
NOS_WET_STRICT="${NOS_WET_STRICT:-1}"
NOS_TIER="${NOS_TIER:-all}"
POST_BLANK_OPEN="${POST_BLANK_OPEN:-0}"

# ── Pretty output (skip colors when piped) ────────────────────────────────
if [[ -t 1 ]]; then
  C_BOLD=$'\033[1m'; C_GRN=$'\033[32m'; C_RED=$'\033[31m'
  C_YLW=$'\033[33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_BOLD=""; C_GRN=""; C_RED=""; C_YLW=""; C_DIM=""; C_RST=""
fi

step() {
  echo
  echo "${C_BOLD}━━━ $1 ━━━${C_RST}"
}

ok()   { echo "${C_GRN}✓${C_RST} $*"; }
fail() { echo "${C_RED}✗${C_RST} $*"; }
warn() { echo "${C_YLW}!${C_RST} $*"; }

# ── Step 1 — wet pytest ───────────────────────────────────────────────────
step "[1/3] Wet state checks (tests/wet/)"

PYTEST_BIN="${PYTEST_BIN:-python3 -m pytest}"
WET_RC=0
if NOS_WET="$NOS_WET_STRICT" $PYTEST_BIN tests/wet -v --tb=short; then
  ok "tests/wet — all green"
else
  WET_RC=$?
  fail "tests/wet — RC=$WET_RC (sections 6/7/9 of the wet-test checklist)"
fi

# ── Step 2 — Tier-2 smoke probe ───────────────────────────────────────────
step "[2/3] Smoke probe (tools/nos-smoke.py)"

SMOKE_RC=0
SMOKE_ARGS=()
if [[ "$NOS_TIER" == "1" || "$NOS_TIER" == "2" ]]; then
  SMOKE_ARGS+=(--tier "$NOS_TIER")
fi

# ${arr[@]+"${arr[@]}"} → expands to nothing when empty under set -u
# (plain "${arr[@]}" trips "unbound variable" with empty arrays in bash 3.2/5.x).
if python3 tools/nos-smoke.py ${SMOKE_ARGS[@]+"${SMOKE_ARGS[@]}"}; then
  ok "nos-smoke — all green"
else
  SMOKE_RC=$?
  fail "nos-smoke — $SMOKE_RC failed probe(s)"
fi

# ── Step 3 — Wing UI deep-links ───────────────────────────────────────────
step "[3/3] Wing UI deep-links"

cat <<EOF
${C_DIM}Open these in a browser to see the recent run state:${C_RST}

  ${C_BOLD}https://wing.${NOS_HOST}/timeline${C_RST}     run-by-run callback plugin telemetry
  ${C_BOLD}https://wing.${NOS_HOST}/hub${C_RST}          systems registry (Tier-1 + app_* Tier-2)
  ${C_BOLD}https://wing.${NOS_HOST}/gdpr${C_RST}         Article 30 processing records
  ${C_BOLD}https://wing.${NOS_HOST}/migrations${C_RST}   migration history (state-manager)
  ${C_BOLD}https://wing.${NOS_HOST}/upgrades${C_RST}     per-service upgrade recipe runs
  ${C_BOLD}https://wing.${NOS_HOST}/coexistence${C_RST}  dual-version provisions (TTL view)

EOF

if [[ "$POST_BLANK_OPEN" == "1" ]]; then
  command -v open >/dev/null 2>&1 \
    && open "https://wing.${NOS_HOST}/timeline" \
    || warn "POST_BLANK_OPEN=1 set but \`open\` not available"
fi

# ── Final verdict ─────────────────────────────────────────────────────────
echo
if (( WET_RC == 0 && SMOKE_RC == 0 )); then
  echo "${C_GRN}${C_BOLD}━━━ POST-BLANK VERDICT: GREEN ━━━${C_RST}"
  exit 0
else
  echo "${C_RED}${C_BOLD}━━━ POST-BLANK VERDICT: RED ━━━${C_RST}"
  echo "${C_DIM}wet=${WET_RC}  smoke=${SMOKE_RC}${C_RST}"
  echo
  echo "Next steps:"
  echo "  - Read failing test name; cross-reference docs/tier2-wet-test-checklist.md"
  echo "    Section ID for the diagnostic recipe."
  echo "  - For smoke failures, ${C_BOLD}python3 tools/nos-smoke.py --failed-only${C_RST}"
  echo "    to filter to the red rows."
  exit 1
fi
