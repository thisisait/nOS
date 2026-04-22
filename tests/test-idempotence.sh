#!/usr/bin/env bash
# ==============================================================================
# nOS idempotence smoke test
#
# Verifies that the state-declarative refactor works — prefix rotation
# propagates the new password into all key services both on blank=true and
# non-blank runs.
#
# WARNING: This script IS destructive — it runs a blank reset and rebuilds
# the stacks. Run only in a dev environment or a prepared VM.
#
# Usage: ./tests/test-idempotence.sh [prefix1] [prefix2] [prefix3]
# ==============================================================================

set -euo pipefail

PREFIX1="${1:-test1}"
PREFIX2="${2:-test2}"
PREFIX3="${3:-test3}"

cd "$(dirname "$0")/.."

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok() { echo -e "${GREEN}OK${NC}   $*"; }
fail() { echo -e "${RED}FAIL${NC} $*"; exit 1; }
info() { echo -e "${YELLOW}--${NC}   $*"; }

check_grafana() {
  local pw="$1"
  local expect="$2"
  local code
  code=$(curl -skL -o /dev/null -w '%{http_code}' -u "admin:${pw}" https://grafana.dev.local/api/org || true)
  if [[ "${code}" == "${expect}" ]]; then
    ok "Grafana ${pw} → ${code}"
  else
    fail "Grafana ${pw} → ${code} (expected ${expect})"
  fi
}

check_authentik() {
  local pw="$1"
  local expect="$2"
  local code
  code=$(curl -skL -o /dev/null -w '%{http_code}' -u "akadmin:${pw}" https://auth.dev.local/api/v3/core/users/me/ || true)
  if [[ "${code}" == "${expect}" ]]; then
    ok "Authentik akadmin:${pw} → ${code}"
  else
    fail "Authentik akadmin:${pw} → ${code} (expected ${expect})"
  fi
}

check_gitea() {
  local pw="$1"
  local expect="$2"
  local code
  code=$(curl -skL -o /dev/null -w '%{http_code}' -u "admin:${pw}" https://git.dev.local/api/v1/version || true)
  if [[ "${code}" == "${expect}" ]]; then
    ok "Gitea admin:${pw} → ${code}"
  else
    fail "Gitea admin:${pw} → ${code} (expected ${expect})"
  fi
}

# ── Test A: blank + prefix rotation ─────────────────────────────────────────
info "TEST A — blank=true with prefix rotation"
info "1/3 Run 1: blank + prefix='${PREFIX1}'"
echo -e "${PREFIX1}\n" | ansible-playbook main.yml -K -e blank=true
check_grafana "${PREFIX1}_pw_grafana" 200
check_authentik "${PREFIX1}_pw_authentik_admin" 200
check_gitea "${PREFIX1}_pw_gitea" 200

info "2/3 Run 2: blank + prefix='${PREFIX2}'"
echo -e "${PREFIX2}\n" | ansible-playbook main.yml -K -e blank=true
check_grafana "${PREFIX1}_pw_grafana" 401
check_grafana "${PREFIX2}_pw_grafana" 200
check_authentik "${PREFIX2}_pw_authentik_admin" 200
check_gitea "${PREFIX2}_pw_gitea" 200

# ── Test B: non-blank + credentials.yml edit ────────────────────────────────
info "TEST B — non-blank run with edited credentials.yml"
info "3/3 Append 'global_password_prefix: \"${PREFIX3}\"' to credentials.yml"
# Note: Phase 5a persists the prefix into credentials.yml automatically;
# this step emulates a manual edit by the user.
grep -q '^global_password_prefix:' credentials.yml 2>/dev/null || \
  echo "global_password_prefix: \"${PREFIX3}\"" >> credentials.yml
sed -i.bak "s/^global_password_prefix:.*/global_password_prefix: \"${PREFIX3}\"/" credentials.yml
rm -f credentials.yml.bak

ansible-playbook main.yml -K
check_grafana "${PREFIX3}_pw_grafana" 200
check_authentik "${PREFIX3}_pw_authentik_admin" 200
check_gitea "${PREFIX3}_pw_gitea" 200

# ── Test C: drift detection (check mode) ────────────────────────────────────
info "TEST C — drift detection (--check --diff)"
ansible-playbook main.yml --check --diff -K 2>&1 | tail -20 || true
info "(manual inspection — expect minimal changes, handlers not fired)"

# ── Test D: destructive gate ────────────────────────────────────────────────
info "TEST D — destructive secrets preservation"
info "Non-blank run should emit WARNING for Infisical/Outline"
ansible-playbook main.yml -K 2>&1 | grep -E "DANGER|destroy_state" || true
info "(grep for 'DANGER' confirms gate works)"

# ── Blueprint status ────────────────────────────────────────────────────────
info "TEST E — Authentik blueprint reconcile status"
docker exec infra-authentik-worker-1 ak shell -c "
from authentik.blueprints.models import BlueprintInstance
for b in BlueprintInstance.objects.filter(name__startswith='nos'):
    print(f'{b.name}: {b.status} (last_applied={b.last_applied})')
" 2>&1 || fail "Blueprint instance query failed"

ok "ALL TESTS PASSED"
