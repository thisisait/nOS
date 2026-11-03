#!/usr/bin/env bash
# =============================================================================
# germinate — a fresh Mac grown back from a nOS spore (tools/spore/nos-spore.sh).
#
# Run from the external disk, in Terminal, as the user who will own the estate:
#   bash /Volumes/SSD1TB/nos-spore/germinate.sh             # dry run: what it would do
#   bash /Volumes/SSD1TB/nos-spore/germinate.sh --confirm
#
# Holds no secret: they are in nos-spore.sparsebundle beside it, opened with the passphrase.
# Order: Xcode CLT -> Homebrew -> clone nOS -> open the spore, check its manifest -> the estate
# clone with config/credentials/OpenTofu state -> ~/.nos -> repos -> bootstrap. It never runs a
# converge: the last lines are the commands for the operator.
# EXPERIMENTAL (2026-11-03): review before a reset.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMG="$HERE/nos-spore.sparsebundle"
SRC="${NOS_SRC_DIR:-$HOME/projects/nOS}"
EST="$HOME/.nos/estate"
PROJECTS="$HOME/projects"
UPSTREAM="${NOS_UPSTREAM:-https://github.com/thisisait/nOS.git}"
CONFIRM=0
[ "${1:-}" = "--confirm" ] && CONFIRM=1

[ "$(uname -s)" = Darwin ] || { echo "REFUSE: germinate is for macOS; Linux uses tools/installer" >&2; exit 64; }
[ -d "$IMG" ] || { echo "REFUSE: no spore at $IMG" >&2; exit 2; }
[ ! -e "$HOME/.nos/secrets.yml" ] || { echo "REFUSE: $HOME/.nos/secrets.yml exists: this Mac already holds an estate" >&2; exit 3; }

if [ "$CONFIRM" = 0 ]; then
  cat <<EOF
DRY RUN. With --confirm, in order:
  1. Xcode Command Line Tools (a system dialog; it waits)
  2. Homebrew (its official installer; asks for the sudo password)
  3. git clone $UPSTREAM -> $SRC
  4. open $IMG (asks the spore passphrase), check MANIFEST.sha256
  5. tools/estate-adopt.sh --dir $EST --from <spore>/estate --branch <recorded ref> --confirm
  6. ~/.nos (0700): secrets, identity map, state, board keys
  7. each carried repo: clone its bundle into $PROJECTS/<name>, remotes back, patch + untracked files
  8. bootstrap.sh steps 03-05 in the estate (config.yml and credentials.yml already there: kept)
Then it prints the converge and restore commands; it runs none of them.
EOF
  exit 0
fi

xcode-select -p >/dev/null 2>&1 || { xcode-select --install || true; echo "Waiting for the Xcode CLT install..."; until xcode-select -p >/dev/null 2>&1; do sleep 5; done; }
command -v brew >/dev/null 2>&1 || [ -x /opt/homebrew/bin/brew ] || \
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"

[ -d "$SRC/.git" ] || { mkdir -p "$(dirname "$SRC")"; git clone "$UPSTREAM" "$SRC"; }

MNT="$(mktemp -d /tmp/nos-spore.XXXXXX)"
echo "Opening the spore (its passphrase)."
hdiutil attach "$IMG" -mountpoint "$MNT" -nobrowse -readonly >/dev/null
trap 'hdiutil detach "$MNT" >/dev/null 2>&1 || true' EXIT
(cd "$MNT" && shasum -a 256 -c --quiet MANIFEST.sha256) || { echo "FAILED: the spore does not match its manifest" >&2; exit 4; }

REF="$(cat "$MNT/estate-ref" 2>/dev/null || echo dev)"
mkdir -p "$HOME/.nos"; chmod 700 "$HOME/.nos"
bash "$SRC/tools/estate-adopt.sh" --dir "$EST" --from "$MNT/estate" --branch "$REF" --confirm
(umask 077; for f in "$MNT"/nos/*; do cp -p "$f" "$HOME/.nos/"; done)
# nos-cli.env from the old Mac names its paths; this home may differ, so the estate decides.
sed -i '' "s#^NOS_SRC=.*#NOS_SRC=$EST#" "$HOME/.nos/nos-cli.env"

mkdir -p "$PROJECTS"
for b in "$MNT"/repos/*.bundle; do
  [ -e "$b" ] || continue
  n="$(basename "$b" .bundle)"
  [ "$n" = estate ] && continue                                    # the estate came from upstream above
  dest="$PROJECTS/$n"
  if [ -e "$dest" ]; then echo "  skip $n: $dest exists"; continue; fi
  git clone -q "$b" "$dest"
  git -C "$dest" remote remove origin
  while read -r name url; do git -C "$dest" remote add "$name" "$url"; done < "$MNT/repos/$n.remotes"
  [ -s "$MNT/repos/$n.patch" ] && git -C "$dest" apply --index "$MNT/repos/$n.patch"
  [ -s "$MNT/repos/$n.untracked.tgz" ] && tar -xzf "$MNT/repos/$n.untracked.tgz" -C "$dest"
  echo "  $n restored into $dest"
done
# Linked worktrees: their branch is in the main repo's bundle; recreate, then their local changes.
for w in "$MNT"/repos/*.worktree; do
  [ -e "$w" ] || continue
  n="$(basename "$w" .worktree)"; read -r main branch < "$w"; dest="$PROJECTS/$n"
  if [ -e "$dest" ] || [ ! -d "$PROJECTS/$main/.git" ]; then echo "  skip worktree $n (exists, or no $main)"; continue; fi
  git -C "$PROJECTS/$main" worktree add -q "$dest" "$branch"
  [ -s "$MNT/repos/$n.patch" ] && git -C "$dest" apply --index "$MNT/repos/$n.patch"
  [ -s "$MNT/repos/$n.untracked.tgz" ] && tar -xzf "$MNT/repos/$n.untracked.tgz" -C "$dest"
  echo "  worktree $n of $main on $branch restored"
done

(cd "$EST" && bash bootstrap/03-ansible.sh && bash bootstrap/04-galaxy.sh && bash bootstrap/05-config.sh)

cat <<EOF

Grown. Next, in this order (each is the operator's):
  cd $EST && ansible-playbook main.yml          # the first converge; installs the nos CLI
  nos dtt import --confirm --bundle <the spore's keap-tables dir, open it again>
  nos --tags restore -e restore_date=YYYY-MM-DD  # service data from the restic repo
  tools/nos-smoke.py --strict
EOF
