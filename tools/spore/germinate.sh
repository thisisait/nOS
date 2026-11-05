#!/usr/bin/env bash
# =============================================================================
# germinate — a fresh Mac grown back from a nOS spore (tools/spore/nos-spore.sh).
#
# Run from the external disk, in Terminal, as the user who will own the estate:
#   bash /Volumes/SSD1TB/nos-spore/germinate.sh                         # dry run: what it would do
#   bash /Volumes/SSD1TB/nos-spore/germinate.sh --confirm [--upstream URL]
#
# Holds no secret: they are in nos-spore.sparsebundle beside it, opened with the passphrase.
# Resumable: what is already in place with the spore's bytes is skipped; a DIFFERENT file or a
# foreign checkout at a destination stops the run (nothing is overwritten). It never runs a
# converge: the last lines are the commands for the operator. bash 3.2 (a fresh Mac's) safe.
# EXPERIMENTAL (2026-11-03): review before a reset. Rehearsal: REHEARSAL.md beside it in the repo.
# =============================================================================
set -euo pipefail

usage="usage: bash $0 [--confirm] [--upstream URL]"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$HERE/$(basename "${BASH_SOURCE[0]}")"
IMG="$HERE/nos-spore.sparsebundle"
SRC="${NOS_SRC_DIR:-$HOME/projects/nOS}"
EST="${NOS_ESTATE_DIR:-$HOME/.nos/estate}"
UPSTREAM="https://github.com/thisisait/nOS.git"
CONFIRM=0
while [ $# -gt 0 ]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --upstream) [ $# -ge 2 ] || { echo "$usage" >&2; exit 64; }; UPSTREAM="$2"; shift 2 ;;
    -h|--help) echo "$usage"; exit 0 ;;
    *) echo "$usage" >&2; exit 64 ;;
  esac
done

[ "$(uname -s)" = Darwin ] || { echo "REFUSE: germinate is for macOS; Linux uses tools/installer" >&2; exit 64; }
[ -d "$IMG" ] || { echo "REFUSE: no spore at $IMG" >&2; exit 2; }

if [ "$CONFIRM" = 0 ]; then
  cat <<EOF
DRY RUN on $(id -un) ($HOME, $(uname -m)). With --confirm, in order (each step skips what is in place):
  1. Xcode Command Line Tools (a system dialog; it waits)
  2. Homebrew (its official installer; asks the sudo password), then \$(brew --prefix)/bin on PATH
  3. open $IMG read-only (the spore passphrase): MANIFEST.sha256, this script's sha256,
     the HOST manifest printed; a different CPU arch is refused
  4. ~/.nos (0700): secrets, identity map, state, board keys; nos-cli.env with the old HOME
     rewritten to $HOME; ~/.ssh and the mkcert CA
  5. every recorded repo into \$HOME/<its old path>: all branches from its bundle (or its remotes),
     remotes back, HEAD (a branch, or the detached commit)
  6. tools/estate-adopt.sh --dir $EST, then the old estate's branches and files into it
  7. every recorded worktree, then each tree's local changes (patch + untracked files)
  8. bootstrap.sh steps 03-05 in the estate (config.yml and credentials.yml already there: kept)
Then it prints the converge and restore commands; it runs none of them.
EOF
  exit 0
fi

refuse() { echo "REFUSE: $*" >&2; exit 3; }

xcode-select -p >/dev/null 2>&1 || { xcode-select --install || true; echo "Waiting for the Xcode CLT install..."; until xcode-select -p >/dev/null 2>&1; do sleep 5; done; }
find_brew() { for b in "$(command -v brew || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -n "$b" ] && [ -x "$b" ] && { echo "$b"; return 0; }; done; return 1; }
BREW="$(find_brew)" || { /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; BREW="$(find_brew)" || { echo "FAILED: no brew after the Homebrew installer" >&2; exit 5; }; }
eval "$("$BREW" shellenv)"
echo "Homebrew: $(brew --prefix)"

MNT="$(mktemp -d /tmp/nos-spore.XXXXXX)"
attached=""
trap '[ -z "$attached" ] || hdiutil detach "$attached" >/dev/null || echo "FAILED: could not detach $attached; eject it in Finder" >&2' EXIT
echo "Opening the spore read-only (its passphrase)."
hdiutil attach "$IMG" -mountpoint "$MNT" -nobrowse -readonly >/dev/null; attached="$MNT"
(cd "$MNT" && shasum -a 256 -c --quiet MANIFEST.sha256) || { echo "FAILED: the spore does not match its manifest" >&2; exit 4; }
[ "$(shasum -a 256 "$SELF" | cut -d' ' -f1)" = "$(cat "$MNT/germinate.sha256")" ] || refuse "$SELF is not the germinate.sh sealed with this spore"
hv() { sed -n "s/^$1=//p" "$MNT/HOST"; }
echo "== the spore's host"; sed 's/^/  /' "$MNT/HOST"
[ "$(hv arch)" = "$(uname -m)" ] || refuse "the spore was sealed on $(hv arch); this Mac is $(uname -m)"
OLD_HOME="$(hv home)"
EST_TREE="$MNT/trees/$(hv estate_rel)"

# A destination holding the spore's bytes is in place; different bytes stop the run.
place() {
  if [ -e "$2" ]; then cmp -s "$1" "$2" || refuse "$2 exists and differs from the spore's copy; move it aside, then re-run"; return 0; fi
  (umask 077; mkdir -p "$(dirname "$2")"); cp -p "$1" "$2"
}
place_tree() { [ ! -d "$1" ] || while IFS= read -r f; do place "$1/$f" "$2/$f"; done < <(cd "$1" && find . -type f | sed 's#^\./##'); }
dest_of() { local rel="${1#"$MNT"/trees/}"; if [ "$1" = "$EST_TREE" ]; then echo "$EST"; else echo "$HOME/$rel"; fi; }

# ── ~/.nos, ~/.ssh, the mkcert CA ──
(umask 077; mkdir -p "$HOME/.nos"); chmod 700 "$HOME/.nos"
for f in "$MNT"/nos/*; do [ "$(basename "$f")" = nos-cli.env ] || place "$f" "$HOME/.nos/$(basename "$f")"; done
# nos-cli.env names the old Mac's paths: every $OLD_HOME path moves here, and NOS_SRC goes last as
# estate-adopt.sh writes it, so an adopt over it leaves the same bytes and a re-run finds it in place.
envf="$(mktemp)"
{ grep -v '^NOS_SRC=' "$MNT/nos/nos-cli.env" | OLD="$OLD_HOME" NEW="$HOME" perl -pe 's/\Q$ENV{OLD}\E(?=[\/"\x27\s]|$)/$ENV{NEW}/g' || true; echo "NOS_SRC=$EST"; } > "$envf"
place "$envf" "$HOME/.nos/nos-cli.env"; rm -f "$envf"
place_tree "$MNT/home" "$HOME"
# The seal log is written after the image closes, so the spore lacks it: its own seal is the record
# (else reseal-due.py reads the restored blank as unsealed and rings). Idempotent across re-runs.
sealed="$(hv sealed)"; seals="$HOME/.nos/spore-seals.log"
[ -z "$sealed" ] || grep -qxF "$sealed" "$seals" 2>/dev/null || echo "$sealed" >> "$seals"
[ ! -d "$HOME/.ssh" ] || chmod 700 "$HOME/.ssh"

# ── repos: all branches from the bundle (or the remotes when every commit is on one), then HEAD ──
restore_repo() {  # $1 the repo's tree in the spore, $2 its destination
  local t="$1" d="$2" kind val name url sha ref
  if [ -d "$d/.git" ]; then
    [ ! -e "$d/.git/spore-restored" ] || { echo "  in place  $d"; return 0; }
    [ -e "$d/.git/spore-restoring" ] || [ "$d" = "$EST" ] || refuse "$d exists and was not grown from this spore; move it aside, then re-run"
  elif [ -e "$d" ]; then refuse "$d exists and is not a git repo"
  else mkdir -p "$(dirname "$d")"; git init -q "$d"; : > "$d/.git/spore-restoring"; fi
  # The repo's own config (core.hooksPath = the pre-push gate, upstreams, nos.estate-ref), old home rewritten.
  if [ -f "$t/git-config" ]; then
    OLD="$OLD_HOME" NEW="$HOME" perl -pe 's/\Q$ENV{OLD}\E(?=[\/"\x27\s]|$)/$ENV{NEW}/g' "$t/git-config" > "$d/.git/config"
  fi
  while read -r name url; do
    if git -C "$d" remote get-url "$name" >/dev/null 2>&1; then git -C "$d" remote set-url "$name" "$url"; else git -C "$d" remote add "$name" "$url"; fi
  done < "$t/remotes"
  if [ -f "$t/repo.bundle" ]; then
    git -C "$d" fetch -q --update-head-ok "$t/repo.bundle" '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*'
  elif [ -s "$t/heads" ]; then
    git -C "$d" fetch -q --all --tags
    while read -r sha ref; do git -C "$d" update-ref "$ref" "$sha"; done < "$t/heads"
  fi
  read -r kind val < "$t/head"
  if [ "$kind" = detached ] && ! git -C "$d" cat-file -e "$val^{commit}" 2>/dev/null; then
    kind=branch; val="$(head -1 "$t/heads" | sed 's#.* refs/heads/##')"; echo "  LOST      $d detached HEAD (accepted at seal); on $val instead"
  fi
  if [ "$kind" = branch ]; then git -C "$d" symbolic-ref HEAD "refs/heads/$val"; else git -C "$d" update-ref --no-deref HEAD "$val"; fi
  [ ! -s "$t/heads" ] || git -C "$d" reset -q --hard   # an empty repo has no commit to check out
  rm -f "$d/.git/spore-restoring"; : > "$d/.git/spore-restored"
  echo "  restored  $d ($kind $val)"
}
echo "== repos"
while IFS= read -r t; do
  [ "$t" = "$EST_TREE" ] || restore_repo "$t" "$(dest_of "$t")"
done < <(find "$MNT/trees" -name head -type f -exec dirname {} \; | sort)
if [ ! -f "$SRC/tools/estate-adopt.sh" ]; then
  [ ! -e "$SRC" ] || refuse "$SRC has no tools/estate-adopt.sh; set NOS_SRC_DIR to the nOS checkout"
  git clone -q "$UPSTREAM" "$SRC"
fi

# ── the estate: its own clone (estate-adopt.sh), then the old estate's branches and files ──
REF="$(cat "$MNT/estate-ref" 2>/dev/null || echo dev)"
if [ ! -d "$EST/.git" ]; then
  up="$(awk '$1=="origin"{print $2}' "$EST_TREE/remotes" 2>/dev/null || true)"
  bash "$SRC/tools/estate-adopt.sh" --dir "$EST" --from "$MNT/estate" --branch "$REF" --upstream "${up:-$UPSTREAM}" --confirm
fi
[ ! -f "$EST_TREE/head" ] || restore_repo "$EST_TREE" "$EST"
place_tree "$MNT/estate" "$EST"

# ── worktrees (parents sort before the worktrees nested in them), then local changes ──
echo "== worktrees"
while IFS= read -r wf; do
  main="$(dest_of "$(dirname "$wf")")"
  while IFS="$(printf '\t')" read -r kind ref rel; do
    d="$HOME/$rel"
    if [ -e "$d/.git" ]; then echo "  in place  $d"; continue; fi
    [ ! -e "$d" ] || refuse "$d exists and is not a worktree"
    if ! git -C "$main" cat-file -e "$ref^{commit}" 2>/dev/null; then echo "  LOST      $d ($kind $ref: accepted at seal)"; continue; fi
    mkdir -p "$(dirname "$d")"
    if [ "$kind" = branch ]; then git -C "$main" worktree add -q "$d" "$ref"; else git -C "$main" worktree add -q --detach "$d" "$ref"; fi
    echo "  added     $d ($kind $ref)"
  done < "$wf"
done < <(find "$MNT/trees" -name worktrees -type f)
echo "== local changes"
while IFS= read -r t; do
  d="$(dest_of "$t")"
  [ -e "$d/.git" ] || refuse "$d has no checkout to carry its local changes into"
  gd="$(git -C "$d" rev-parse --absolute-git-dir)"
  [ ! -e "$gd/spore-changes" ] || { echo "  in place  $d"; continue; }
  [ ! -s "$t/changes.patch" ] || git -C "$d" apply --index "$t/changes.patch"
  [ ! -f "$t/untracked.tgz" ] || tar -xzf "$t/untracked.tgz" -C "$d"
  : > "$gd/spore-changes"
  echo "  applied   $d"
done < <(find "$MNT/trees" -type f \( -name changes.patch -o -name untracked.tgz \) -exec dirname {} \; | sort -u)

(cd "$EST" && bash bootstrap/03-ansible.sh && bash bootstrap/04-galaxy.sh && bash bootstrap/05-config.sh)
hdiutil detach "$MNT" >/dev/null || { echo "FAILED: could not detach $MNT; eject it in Finder" >&2; exit 5; }
attached=""

cat <<EOF

Grown. Next, in this order (each is the operator's):
  cd $EST && ansible-playbook main.yml          # the first converge; installs the nos CLI
  nos dtt import --confirm --bundle <the spore's keap-tables dir, open it again>
  nos --tags restore -e restore_date=YYYY-MM-DD  # service data from the restic repo
  tools/nos-smoke.py --strict
EOF
