#!/usr/bin/env bash
# tools/tofu-authentik-reconcile.sh — tofu-state ⇄ live-Authentik PK reconcile.
#
# tofu tracks each service's Authentik provider by integer PK (resource id).
# Those PKs can drift out from under the state — a blank state-reset that didn't
# fully align, a provider recreate, a manual change — so `tofu plan` reads a
# dangerous in-place client_id/external_host flip and the destroy guard REFUSES,
# even though the live SSO is correct. This re-points each module.service[*]
# provider (+ proxy outpost attachment + application) at its CURRENT live PK.
#
# DRIFT-CONDITIONAL: it compares the state's recorded PK to the live PK and acts
# ONLY on the services that drifted (a no-op when already aligned), so it is cheap
# enough to run as a `tofu plan` PREFLIGHT on every converge. Services not in the
# tofu state (disabled / not tofu-managed, e.g. mailpit) are skipped.
#
# It reconciles IDENTITY ONLY (which live PK is this slug's provider) — never
# attributes — so the plan that runs AFTER it still compares desired-vs-live and a
# REAL config change still trips the guard. Source of truth = live
# application.slug → application.provider (apps import by slug, never desync).
# Import + state ops ONLY; never mutates the tenant; backs up state first.
#
# Durable fix for the recurring desync (docs/plans/v07-no-auto-adopt.md
# § LIVE ROOT-CAUSE). Wired into tasks/tofu-authentik.yml as `--preflight`.
#
# Usage:
#   tools/tofu-authentik-reconcile.sh             # reconcile drifted + verify plan
#   tools/tofu-authentik-reconcile.sh --preflight # reconcile drifted, skip plan (for the playbook)
#   tools/tofu-authentik-reconcile.sh --dry-run   # print the drift + ops, touch nothing
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$REPO_ROOT/terraform/authentik"
REG="$REPO_ROOT/state/tofu-authentik-services.yml"
SECRETS="${HOME}/.nos/secrets.yml"
PORT="${AUTHENTIK_PORT:-9003}"
API="http://127.0.0.1:${PORT}/api/v3"

MODE=full; DRY=0
for a in "$@"; do
  case "$a" in
    --preflight) MODE=preflight ;;
    --dry-run)   DRY=1 ;;
    *) echo "[reconcile] unknown arg: $a" >&2; exit 2 ;;
  esac
done

command -v tofu >/dev/null || { echo "[reconcile] tofu not on PATH"; exit 2; }
[ -f "$SECRETS" ] || { echo "[reconcile] $SECRETS missing"; exit 2; }
[ -f "$TF_DIR/nos.auto.tfvars.json" ] || { echo "[reconcile] tfvars missing — run the playbook once to render it"; exit 2; }
[ -f "$TF_DIR/terraform.tfstate" ] || { echo "[reconcile] no state yet — nothing to reconcile"; exit 0; }

TOKEN="$(python3 -c "import yaml,os;print(yaml.safe_load(open(os.path.expanduser('$SECRETS'))).get('authentik_bootstrap_token',''))")"
auth=(-H "Authorization: Bearer ${TOKEN}")
curl -fsS -o /dev/null "${auth[@]}" "$API/core/users/me/" || { echo "[reconcile] token/API auth failed on $API"; exit 2; }
echo "[reconcile] tenant API: $API  mode=$MODE dry=$DRY"

cd "$TF_DIR"

# embedded outpost uuid — for proxy attachment ids "<outpost>:<pk>"
OUTPOST_ID="$(curl -fsS "${auth[@]}" "$API/outposts/instances/?page_size=200" \
  | python3 -c "import json,sys
for o in json.load(sys.stdin)['results']:
    if o.get('name')=='authentik Embedded Outpost': print(o['pk']); break")"
[ -n "$OUTPOST_ID" ] || { echo "[reconcile] could not resolve embedded outpost id"; exit 2; }

# live application.slug -> provider PK (source of truth)
APPMAP="$(curl -fsS "${auth[@]}" "$API/core/applications/?page_size=200" \
  | python3 -c "import json,sys
for a in json.load(sys.stdin)['results']:
    if a.get('provider') is not None: print(a['slug'], a['provider'])")"
pk_for() { echo "$APPMAP" | awk -v s="$1" '$1==s{print $2; exit}'; }

# state slug -> recorded provider PK (drift detection — read the tfstate once)
STATEPK="$(python3 -c "
import json
s=json.load(open('terraform.tfstate'))
for r in s.get('resources',[]):
    m=r.get('module','')
    if m.startswith('module.service[\"') and r.get('type') in ('authentik_provider_oauth2','authentik_provider_proxy'):
        slug=m.split('\"')[1]
        for inst in r.get('instances',[]):
            print(slug, inst.get('attributes',{}).get('id',''))")"
statepk_for() { echo "$STATEPK" | awk -v s="$1" '$1==s{print $2; exit}'; }

RECON=0; ALIGNED=0; SKIP=0; FAILS=0
: > /tmp/reconcile-err.log
BACKED_UP=0
backup_once() {
  [ "$DRY" = 1 ] && return
  [ "$BACKED_UP" = 1 ] && return
  cp terraform.tfstate "terraform.tfstate.reconcile-bak-$(date +%Y%m%d-%H%M%S)"
  echo "[reconcile] state backup written"; BACKED_UP=1
}

reimport() {  # <address> <id>
  if [ "$DRY" = 1 ]; then echo "    DRY rm+import: ${1##*service} <- $2"; return; fi
  backup_once
  tofu state rm "$1" >/dev/null 2>&1 || true
  if tofu import -input=false "$1" "$2" >>/tmp/reconcile-err.log 2>&1; then
    echo "    ok: ${1##*.} <- $2"
  else
    echo "    FAIL import: $1 <- $2"; FAILS=$((FAILS+1))
  fi
}

while IFS=' ' read -r slug mode; do
  [ -z "$slug" ] && continue
  spk="$(statepk_for "$slug")"
  [ -z "$spk" ] && { SKIP=$((SKIP+1)); continue; }   # not in tofu state → not managed
  pk="$(pk_for "$slug")"
  [ -z "$pk" ] && { echo "  WARN $slug: in state but no live application (pk unknown) — skip"; SKIP=$((SKIP+1)); continue; }
  if [ "$spk" = "$pk" ]; then ALIGNED=$((ALIGNED+1)); continue; fi
  echo "  DRIFT $slug: state pk=$spk → live pk=$pk (mode=$mode)"
  if [ "$mode" = "native_oidc" ]; then
    reimport "module.service[\"$slug\"].authentik_provider_oauth2.this[0]" "$pk"
  else
    reimport "module.service[\"$slug\"].authentik_provider_proxy.this[0]" "$pk"
    reimport "module.service[\"$slug\"].authentik_outpost_provider_attachment.embedded[0]" "$OUTPOST_ID:$pk"
  fi
  reimport "module.service[\"$slug\"].authentik_application.this" "$slug"
  RECON=$((RECON+1))
done < <(python3 -c "
import yaml
for s in yaml.safe_load(open('$REG'))['tofu_authentik_services']:
    print(s['slug'], s['mode'])")

echo "[reconcile] reconciled=$RECON aligned=$ALIGNED skipped=$SKIP import-fails=$FAILS"
[ "$DRY" = 1 ] && exit 0
[ "$MODE" = preflight ] && exit 0

echo "[reconcile] tofu plan (goal: 0 to add/change/destroy)..."
tofu plan -input=false -no-color 2>&1 | grep -E "Plan:|No changes|would change .* immutable|Error:" | tail -5
