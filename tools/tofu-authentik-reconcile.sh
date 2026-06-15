#!/usr/bin/env bash
# tools/tofu-authentik-reconcile.sh — STOPGAP tofu-state ⇄ live-Authentik reconcile.
#
# The tofu state tracks each service's Authentik provider by integer PK
# (resource id). When the imperative converge layer recreates providers, their
# PKs shift out from under the state, so `tofu plan` reads a dangerous in-place
# client_id/external_host flip and the destroy guard REFUSES (correctly). This
# re-points every module.service[*] provider (+ proxy outpost attachment +
# application) at its CURRENT live PK so the next plan reads NO-OP.
#
# Source of truth = live application.slug -> application.provider (apps import
# by SLUG, which never desyncs). Import + state ops ONLY — never mutates the
# tenant. Run before `ansible-playbook main.yml --tags tofu-authentik` whenever
# the guard refuses on a stale-PK drift.
#
# This is a STOPGAP. The recurrence root cause (who churns the PKs) + the durable
# fix (stable-key tracking / stop the churn) live in
# docs/plans/v07-no-state-reconciliation.md.
#
# Usage:
#   tools/tofu-authentik-reconcile.sh             # reconcile + verify plan
#   tools/tofu-authentik-reconcile.sh --dry-run   # print the ops, touch nothing
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$REPO_ROOT/terraform/authentik"
REG="$REPO_ROOT/state/tofu-authentik-services.yml"
SECRETS="${HOME}/.nos/secrets.yml"
PORT="${AUTHENTIK_PORT:-9003}"
API="http://127.0.0.1:${PORT}/api/v3"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

command -v tofu >/dev/null || { echo "[reconcile] tofu not on PATH"; exit 2; }
[ -f "$SECRETS" ] || { echo "[reconcile] $SECRETS missing"; exit 2; }
[ -f "$TF_DIR/nos.auto.tfvars.json" ] || { echo "[reconcile] tfvars missing — run the playbook once to render it"; exit 2; }

TOKEN="$(python3 -c "import yaml,os;print(yaml.safe_load(open(os.path.expanduser('$SECRETS'))).get('authentik_bootstrap_token',''))")"
auth=(-H "Authorization: Bearer ${TOKEN}")
curl -fsS -o /dev/null "${auth[@]}" "$API/core/users/me/" || { echo "[reconcile] token/API auth failed on $API"; exit 2; }
echo "[reconcile] tenant API: $API  (dry-run=$DRY)"

cd "$TF_DIR"

# embedded outpost uuid — needed for proxy attachment ids "<outpost>:<pk>"
OUTPOST_ID="$(curl -fsS "${auth[@]}" "$API/outposts/instances/?page_size=200" \
  | python3 -c "import json,sys
for o in json.load(sys.stdin)['results']:
    if o.get('name')=='authentik Embedded Outpost': print(o['pk']); break")"
[ -n "$OUTPOST_ID" ] || { echo "[reconcile] could not resolve embedded outpost id"; exit 2; }

# live application.slug -> provider PK (the source of truth)
APPMAP="$(curl -fsS "${auth[@]}" "$API/core/applications/?page_size=200" \
  | python3 -c "import json,sys
for a in json.load(sys.stdin)['results']:
    if a.get('provider') is not None: print(a['slug'], a['provider'])")"
pk_for() { echo "$APPMAP" | awk -v s="$1" '$1==s{print $2; exit}'; }

# backup state (real run only)
if [ "$DRY" = 0 ]; then
  ts="$(date +%Y%m%d-%H%M%S)"
  cp terraform.tfstate "terraform.tfstate.reconcile-bak-$ts"
  echo "[reconcile] state backup -> terraform.tfstate.reconcile-bak-$ts"
fi

: > /tmp/reconcile-err.log
FAILS=0; DONE=0; SKIP=0

reimport() {  # <address> <id>
  if [ "$DRY" = 1 ]; then echo "    DRY rm+import: $1 <- $2"; return; fi
  tofu state rm "$1" >/dev/null 2>&1 || true
  if tofu import -input=false "$1" "$2" >>/tmp/reconcile-err.log 2>&1; then
    echo "    ok: ${1##*.} <- $2"
  else
    echo "    FAIL import: $1 <- $2"; FAILS=$((FAILS+1))
  fi
}

while IFS=' ' read -r slug mode; do
  [ -z "$slug" ] && continue
  pk="$(pk_for "$slug")"
  if [ -z "$pk" ]; then echo "  SKIP $slug (no live application — not deployed)"; SKIP=$((SKIP+1)); continue; fi
  echo "  $slug (mode=$mode pk=$pk)"
  if [ "$mode" = "native_oidc" ]; then
    reimport "module.service[\"$slug\"].authentik_provider_oauth2.this[0]" "$pk"
  else
    reimport "module.service[\"$slug\"].authentik_provider_proxy.this[0]" "$pk"
    reimport "module.service[\"$slug\"].authentik_outpost_provider_attachment.embedded[0]" "$OUTPOST_ID:$pk"
  fi
  reimport "module.service[\"$slug\"].authentik_application.this" "$slug"
  DONE=$((DONE+1))
done < <(python3 -c "
import yaml
for s in yaml.safe_load(open('$REG'))['tofu_authentik_services']:
    print(s['slug'], s['mode'])")

echo "[reconcile] services=$DONE skipped=$SKIP import-fails=$FAILS  (errs: /tmp/reconcile-err.log)"
[ "$DRY" = 1 ] && exit 0

echo "[reconcile] tofu plan (goal: 0 to add/change/destroy)..."
tofu plan -input=false -no-color 2>&1 | grep -E "Plan:|No changes|would change .* immutable|Error:" | tail -5
