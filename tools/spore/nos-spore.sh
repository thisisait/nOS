#!/usr/bin/env bash
# =============================================================================
# nos-spore — what a factory reset must not take, sealed on an external disk.
#
# A spore is the estate's dormant form: the few things no converge can regenerate (the secret
# master, config + credentials, the OpenTofu state, identities and board keys, the DataTables,
# every repo's work that no remote holds), in an AES-256 encrypted sparse image whose passphrase
# only the operator types. germinate.sh, beside it and holding no secret, grows a fresh Mac back.
# Service data is NOT in here: it is the restic repo (backup), which this only checks is fresh.
#
#   tools/spore/nos-spore.sh --to /Volumes/SSD1TB/nos-spore              # dry run: the inventory
#   tools/spore/nos-spore.sh --to /Volumes/SSD1TB/nos-spore --confirm    # seal it (asks a passphrase)
#
# EXPERIMENTAL (2026-11-03): review before a reset; it writes only under --to.
# =============================================================================
set -euo pipefail

TO="" PROJECTS="$HOME/projects" CONFIRM=0
EST="${NOS_ESTATE_DIR:-$HOME/.nos/estate}"
NOS_HOME="$HOME/.nos"
while [ $# -gt 0 ]; do
  case "$1" in
    --to) TO="$2"; shift 2 ;;
    --projects) PROJECTS="$2"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    *) echo "usage: $0 --to /Volumes/<disk>/<dir> [--projects DIR] [--confirm]" >&2; exit 64 ;;
  esac
done
[ -n "$TO" ] || { echo "usage: $0 --to /Volumes/<disk>/<dir> [--projects DIR] [--confirm]" >&2; exit 64; }
case "$TO" in
  /Volumes/*/*) ;;
  *) echo "REFUSE: --to must be a directory on an external volume (/Volumes/<disk>/...): the internal disk is what a reset wipes" >&2; exit 64 ;;
esac
[ -d "$(echo "$TO" | cut -d/ -f1-3)" ] || { echo "REFUSE: $(echo "$TO" | cut -d/ -f1-3) is not mounted" >&2; exit 2; }

# ── 1. The files (each must exist; a missing one is named, never skipped silently) ──
files=(
  "$NOS_HOME/secrets.yml"          # the secret master: every derived password
  "$NOS_HOME/identity-map.yml"
  "$NOS_HOME/state.yml"
  "$NOS_HOME/blank-runs.jsonl"
  "$NOS_HOME/nos-cli.env"
  "$NOS_HOME/paperclip-board.token"
  "$NOS_HOME/paperclip-ceo-invite.txt"
)
# What tools/estate-adopt.sh --from carries: config, credentials, *.bak.yml, OpenTofu state.
estate=("$EST/config.yml" "$EST/credentials.yml")
for f in "$EST"/*.bak.yml "$EST"/terraform/*/terraform.tfstate "$EST"/terraform/*/terraform.tfstate.backup; do
  [ -f "$f" ] && estate+=("$f")
done

missing=0
echo "== files (into the encrypted image)"
for f in "${files[@]}" "${estate[@]}"; do
  if [ -f "$f" ]; then printf '  %-8s %s\n' "$(du -h "$f" | cut -f1)" "${f/#$HOME/~}"
  else printf '  MISSING  %s\n' "${f/#$HOME/~}"; missing=$((missing + 1)); fi
done

# ── 2. Repos: work that no remote holds (unpushed commits, local changes, untracked files) ──
echo "== repos under ${PROJECTS/#$HOME/~} (a bundle for each one with work no remote holds)"
bundle=()
for g in "$PROJECTS"/*/.git "$EST/.git"; do
  [ -e "$g" ] || continue
  r="$(dirname "$g")"
  remotes="$(git -C "$r" remote | wc -l | tr -d ' ')"
  ahead="$(git -C "$r" log --branches --not --remotes --oneline 2>/dev/null | wc -l | tr -d ' ')"
  dirty="$(git -C "$r" status --porcelain --untracked-files=normal 2>/dev/null | wc -l | tr -d ' ')"
  if [ -f "$g" ]; then
    # A linked worktree: its branches are in the main repo's bundle; only its local changes travel.
    main="$(basename "$(dirname "$(git -C "$r" rev-parse --path-format=absolute --git-common-dir)")")"
    printf '  CARRY  %-28s worktree of %s on %s, local-changes=%s\n' "$(basename "$r")" "$main" "$(git -C "$r" rev-parse --abbrev-ref HEAD)" "$dirty"
    bundle+=("$r")
  elif [ "$remotes" = 0 ] || [ "$ahead" != 0 ] || [ "$dirty" != 0 ]; then
    printf '  CARRY  %-28s remotes=%s unpushed-commits=%s local-changes=%s\n' "$(basename "$r")" "$remotes" "$ahead" "$dirty"
    bundle+=("$r")
    # Worktrees elsewhere (agent worktrees under .claude/): commits ride the bundle, local changes do not.
    git -C "$r" worktree list --porcelain | sed -n 's/^worktree //p' | while read -r wt; do
      case "$wt" in "$r"|"$PROJECTS"/*/) continue ;; esac
      [ "$(dirname "$wt")" = "$PROJECTS" ] && continue
      n_dirty="$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
      if [ "$n_dirty" != 0 ]; then
        printf '  LOST   %s: %s uncommitted change(s) in %s; commit them first\n' "$(basename "$r")" "$n_dirty" "${wt/#$HOME/~}"
      fi
    done
  else
    printf '  ok     %-28s every commit is on a remote, tree clean\n' "$(basename "$r")"
  fi
done

# ── 3. Service data lives in the backup: is it fresh? ──
echo "== backup (service data is restored from it, not carried here)"
last="$(python3 -c 'import json,os,time;d=json.load(open(os.path.expanduser("~/.nos/backup-status.json")));print(int((time.time()-d.get("last_run",0))/3600))' 2>/dev/null || echo "?")"
repo="$(grep -E '^restic_repo:' "$EST/config.yml" 2>/dev/null | sed 's/^restic_repo: *//; s/"//g' || true)"
echo "  last backup run: ${last} h ago; restic repo: ${repo:-not set in config.yml}"
stale=0
if [ "$last" = "?" ] || [ "$last" -gt 24 ]; then echo "  STALE: run the backup (and backup-verify) before a reset"; stale=1; fi
if [ -n "$repo" ] && [ ! -d "$repo" ]; then echo "  MISSING: the restic repo $repo is not reachable"; stale=1; fi

echo "== DataTables: exported into the image by tools/keap-tables.py export"
if [ "$CONFIRM" = 0 ]; then
  echo ""
  echo "DRY RUN: nothing written. ${missing} file(s) missing, ${#bundle[@]} repo(s) to carry, backup stale=${stale}."
  echo "Seal it: $0 --to $TO --confirm   (asks a new passphrase; keep it off this machine)"
  exit 0
fi
[ "$missing" = 0 ] || { echo "REFUSE: ${missing} file(s) missing; fix or say why before sealing" >&2; exit 3; }
[ "$stale" = 0 ] || { echo "REFUSE: the backup is stale or its repo unreachable; a spore does not carry service data" >&2; exit 3; }

# ── Seal ──
mkdir -p "$TO"
IMG="$TO/nos-spore.sparsebundle"
[ ! -e "$IMG" ] || { echo "REFUSE: $IMG exists; move it aside (a spore is never overwritten)" >&2; exit 3; }
echo "Creating $IMG (AES-256). hdiutil asks for a NEW passphrase now."
hdiutil create -size 8g -type SPARSEBUNDLE -fs APFS -encryption AES-256 -volname nos-spore "$IMG" >/dev/null
MNT="$(mktemp -d /tmp/nos-spore.XXXXXX)"
echo "Opening it (the same passphrase)."
hdiutil attach "$IMG" -mountpoint "$MNT" -nobrowse >/dev/null
trap 'hdiutil detach "$MNT" >/dev/null 2>&1 || true' EXIT
umask 077
mkdir -p "$MNT/nos" "$MNT/estate" "$MNT/repos" "$MNT/keap-tables"
for f in "${files[@]}"; do cp -p "$f" "$MNT/nos/"; done
for f in "${estate[@]}"; do
  rel="${f#"$EST"/}"; mkdir -p "$MNT/estate/$(dirname "$rel")"; cp -p "$f" "$MNT/estate/$rel"
done
for r in "${bundle[@]}"; do
  n="$(basename "$r")"
  if [ -f "$r/.git" ]; then
    main="$(basename "$(dirname "$(git -C "$r" rev-parse --path-format=absolute --git-common-dir)")")"
    printf '%s %s\n' "$main" "$(git -C "$r" rev-parse --abbrev-ref HEAD)" > "$MNT/repos/$n.worktree"
  else
    git -C "$r" bundle create "$MNT/repos/$n.bundle" --all
  fi
  git -C "$r" diff HEAD --binary > "$MNT/repos/$n.patch"
  git -C "$r" ls-files -o --exclude-standard -z | (cd "$r" && xargs -0 tar -czf "$MNT/repos/$n.untracked.tgz" 2>/dev/null || true)
  git -C "$r" remote -v | awk '$3=="(fetch)"{print $1, $2}' > "$MNT/repos/$n.remotes"
done
git -C "$EST" rev-parse --abbrev-ref 'estate@{upstream}' 2>/dev/null | sed 's#^origin/##' > "$MNT/estate-ref" || echo dev > "$MNT/estate-ref"
KEAP_TABLES_BUNDLE_DIR="$MNT/keap-tables" python3 "$EST/tools/keap-tables.py" export --confirm
(cd "$MNT" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256)
# Read it back from the image: what was written is what is there.
(cd "$MNT" && shasum -a 256 -c --quiet MANIFEST.sha256) || { echo "FAILED: the image does not read back" >&2; exit 4; }
cp "$(dirname "$0")/germinate.sh" "$TO/germinate.sh"
echo "Sealed: $IMG ($(wc -l < "$MNT/MANIFEST.sha256" | tr -d ' ') files, read back OK). On the new Mac: bash $TO/germinate.sh"
