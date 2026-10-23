#!/usr/bin/env bash
# =============================================================================
# estate-adopt.sh — give a host's estate its own main clone of nOS
#
# The estate's persisted paths (launchd plists, Pulse jobs, the thalamus's NOS_REPO_ROOT) point
# at the MAIN checkout of the repo the converge runs from (tasks/preflight-checkout-current.yml).
# A host whose estate lives in a worktree of a development clone therefore runs the development
# clone's commit; measured 2026-10-14 on a client host, 354 commits apart. This builds the layout
# that cannot split:
#
#   <dir>            main clone, branch `estate` tracking origin/<branch>; holds config.yml and
#                    credentials.yml; NOS_SRC in ~/.nos/nos-cli.env points here. Converge here.
#   origin           the upstream (fetch only; push disabled)
#   fork             the contributor's fork, if given: fix branches are pushed here, PRs go upstream
#   fix worktrees    git -C <dir> worktree add ../<dir>-fix-<x> -b fix/<x> origin/<branch>
#
# Dry-run unless --confirm. It never deletes the old checkout: retire it after a green converge.
#
#   tools/estate-adopt.sh --dir ~/project/nos [--from ~/project/nos-estate] [--fork URL]
#                         [--upstream URL] [--branch dev] [--confirm]
# =============================================================================
set -euo pipefail

UPSTREAM="https://github.com/thisisait/nOS.git"
BRANCH="dev"
DIR="" FROM="" FORK="" CONFIRM=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --from) FROM="$2"; shift 2 ;;
    --fork) FORK="$2"; shift 2 ;;
    --upstream) UPSTREAM="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "estate-adopt: unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$DIR" ] || { echo "estate-adopt: --dir is required" >&2; exit 2; }
DIR="${DIR/#\~/$HOME}"
FROM="${FROM/#\~/$HOME}"
ENVF="$HOME/.nos/nos-cli.env"

if [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  echo "REFUSE: $DIR exists and is not empty — pick a new directory; nothing is overwritten." >&2
  exit 1
fi
if [ -n "$FROM" ] && [ ! -f "$FROM/config.yml" ]; then
  echo "REFUSE: --from $FROM has no config.yml to carry over." >&2
  exit 1
fi
carry=()
if [ -n "$FROM" ]; then
  for f in "$FROM"/config.yml "$FROM"/credentials.yml "$FROM"/*.bak.yml; do
    if [ -f "$f" ]; then carry+=("$(basename "$f")"); fi
  done
  # OpenTofu state is gitignored runtime state of the tree it ran in (live 2026-10-23: without
  # it the estate planned to re-create 13 Authentik providers that exist). Reconcile backups stay.
  for f in "$FROM"/terraform/*/terraform.tfstate "$FROM"/terraform/*/terraform.tfstate.backup; do
    if [ -f "$f" ]; then carry+=("${f#"$FROM"/}"); fi
  done
fi

echo "plan:"
echo "  clone   $UPSTREAM -> $DIR (origin, push disabled), branch estate tracking origin/$BRANCH"
if [ -n "$FORK" ]; then echo "  remote  fork = $FORK"; fi
if [ ${#carry[@]} -gt 0 ]; then echo "  copy    ${carry[*]} from $FROM (credentials* and tofu state chmod 600)"; fi
echo "  galaxy  roles from ${FROM:-ansible-galaxy (requirements.yml)} into $DIR/roles"
echo "  env     NOS_SRC=$DIR in $ENVF (previous kept as $ENVF.prev)"
if [ "$CONFIRM" -ne 1 ]; then
  echo "dry run: nothing changed. Re-run with --confirm."
  exit 0
fi

git clone --quiet --origin origin "$UPSTREAM" "$DIR"
git -C "$DIR" remote set-url --push origin DISABLED
if [ -n "$FORK" ]; then git -C "$DIR" remote add fork "$FORK"; fi
git -C "$DIR" switch --quiet -c estate --track "origin/$BRANCH"
for f in "${carry[@]+"${carry[@]}"}"; do
  mkdir -p "$(dirname "$DIR/$f")"
  cp -p "$FROM/$f" "$DIR/$f"
  case "$f" in credentials*|*/terraform.tfstate*) chmod 600 "$DIR/$f" ;; esac
done
# Galaxy roles (requirements.yml) install into roles/ but are gitignored, so a clone has none.
# From the old tree: the roles it ran with, i.e. every roles/ dir the fresh clone does not track.
if [ -n "$FROM" ] && [ -d "$FROM/roles" ]; then
  mkdir -p "$DIR/roles"
  for d in "$FROM"/roles/*/; do
    n="$(basename "$d")"
    if [ ! -e "$DIR/roles/$n" ]; then cp -R "$d" "$DIR/roles/$n"; echo "  galaxy  $n (from $FROM)"; fi
  done
elif command -v ansible-galaxy >/dev/null; then
  (cd "$DIR" && ansible-galaxy role install -r requirements.yml -p roles)
else
  echo "  galaxy  ansible-galaxy not on PATH: run 'ansible-galaxy role install -r requirements.yml -p roles' in $DIR" >&2
fi
mkdir -p "$(dirname "$ENVF")"
if [ -f "$ENVF" ]; then
  cp -p "$ENVF" "$ENVF.prev"
  { grep -v '^NOS_SRC=' "$ENVF" || true; echo "NOS_SRC=$DIR"; } > "$ENVF.new"
else
  echo "NOS_SRC=$DIR" > "$ENVF.new"
fi
mv "$ENVF.new" "$ENVF"

echo "adopted: $DIR at $(git -C "$DIR" log --oneline -1)"
echo "next:    cd $DIR && nos   (the estate now converges from its own main clone)"
echo "then:    after a green converge, retire the old checkout${FROM:+ ($FROM)} and its worktrees"
