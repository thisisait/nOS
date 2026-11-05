#!/usr/bin/env bash
# =============================================================================
# nos-spore — what a factory reset must not take, sealed on an external disk.
#
# A spore is the estate's dormant form: the few things no converge can regenerate (the secret
# master, config + credentials, the OpenTofu state, identities and board keys, the DataTables,
# ~/.ssh, the mkcert CA, every repo's branches and worktrees), in an AES-256 encrypted sparse
# image whose passphrase only the operator types. germinate.sh, beside it and holding no secret,
# grows a fresh Mac back. Service data is NOT in here: it is the restic repo, checked fresh (< 6 h).
#
#   tools/spore/nos-spore.sh --to /Volumes/SSD1TB/nos-spore              # dry run: the inventory
#   tools/spore/nos-spore.sh --to /Volumes/SSD1TB/nos-spore --confirm    # seal it (asks a passphrase)
#     --accept-loss   seal although LOST rows exist (they are listed in the image's HOST file)
#
# Seal again after every blank and right before a reset: a blank re-mints the secret master.
# EXPERIMENTAL (2026-11-03): review before a reset; it writes under --to, plus one line to
# ~/.nos/spore-seals.log (read by reseal-due.py, the operator task). Rehearsal: REHEARSAL.md.
# =============================================================================
set -euo pipefail
export GIT_OPTIONAL_LOCKS=0  # the scan reads: git status must not refresh (write) any index

usage="usage: $0 --to /Volumes/<disk>/<dir> [--projects DIR] [--confirm [--accept-loss]]"
TO="" PROJECTS="$HOME/projects" CONFIRM=0 ACCEPT_LOSS=0
EST="${NOS_ESTATE_DIR:-$HOME/.nos/estate}"
NOS_HOME="$HOME/.nos"
while [ $# -gt 0 ]; do
  case "$1" in
    --to) [ $# -ge 2 ] || { echo "$usage" >&2; exit 64; }; TO="$2"; shift 2 ;;
    --projects) [ $# -ge 2 ] || { echo "$usage" >&2; exit 64; }; PROJECTS="${2%/}"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    --accept-loss) ACCEPT_LOSS=1; shift ;;
    *) echo "$usage" >&2; exit 64 ;;
  esac
done
[ -n "$TO" ] || { echo "$usage" >&2; exit 64; }
case "$TO" in /*) ;; *) echo "REFUSE: --to must be an absolute path" >&2; exit 64 ;; esac
case "$PROJECTS/" in "$HOME"/*) ;; *) echo "REFUSE: --projects must be under \$HOME (germinate restores paths relative to it)" >&2; exit 64 ;; esac
# The volume decides, not the path: '/Volumes/Macintosh HD/x' is the internal disk a reset wipes.
anc="$TO"; while [ ! -d "$anc" ]; do anc="$(dirname "$anc")"; done
vol="$(/bin/df -P "$anc" | awk 'NR==2{sub(/^.*%[ ]+/, ""); print}')"
if ! diskutil info "$vol" 2>/dev/null | grep -qE '^ *(Internal: +No|Device Location: +External|Removable Media: +Removable)'; then
  echo "REFUSE: $TO is on volume '$vol', which diskutil does not report as external or removable" >&2; exit 64
fi

kb=0  # the image size estimate: everything that goes in, counted once
add_kb() { kb=$((kb + $(du -sk "$1" | cut -f1))); }

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
# What tools/estate-adopt.sh --from carries: config, credentials, *.bak.yml.
estate=("$EST/config.yml" "$EST/credentials.yml")
for f in "$EST"/*.bak.yml; do
  [ -f "$f" ] && estate+=("$f")
done

missing=0
echo "== files (into the encrypted image)"
for f in "${files[@]}" "${estate[@]}"; do
  if [ -f "$f" ]; then printf '  %-8s %s\n' "$(du -h "$f" | cut -f1)" "${f/#$HOME/~}"; add_kb "$f"
  else printf '  MISSING  %s\n' "${f/#$HOME/~}"; missing=$((missing + 1)); fi
done
# Home trees: SSH keys, and the mkcert CA every estate certificate chains to.
homedirs=()
[ -d "$HOME/.ssh" ] && homedirs+=("$HOME/.ssh")
# OpenTofu state left the checkout for ~/.nos/tofu (2026-11-05); germinate places it back as a tree.
[ -d "$NOS_HOME/tofu" ] && homedirs+=("$NOS_HOME/tofu")
CAROOT=""
if command -v mkcert >/dev/null 2>&1; then
  CAROOT="$(mkcert -CAROOT)"
  case "$CAROOT/" in
    "$HOME"/*) if [ -d "$CAROOT" ]; then homedirs+=("$CAROOT"); else printf '  none     %s (no mkcert CA on this Mac)\n' "${CAROOT/#$HOME/~}"; fi ;;
    *) printf '  MISSING  %s (mkcert CAROOT outside $HOME: not carried)\n' "$CAROOT"; missing=$((missing + 1)) ;;
  esac
fi
for d in ${homedirs[@]+"${homedirs[@]}"}; do printf '  %-8s %s/\n' "$(du -sh "$d" | cut -f1)" "${d/#$HOME/~}"; add_kb "$d"; done

# ── 2. Repos: every branch, HEAD and worktree is recorded; a bundle where no remote holds the work ──
# Sets: branches remotes ahead dirty untracked (counts) for the repo or worktree $1.
repo_facts() {
  branches="$(git -C "$1" for-each-ref refs/heads | wc -l | tr -d ' ')"
  remotes="$(git -C "$1" remote | wc -l | tr -d ' ')"
  ahead=0  # an empty repo has no log to walk (git log fails, and pipefail would abort the scan)
  [ "$branches" = 0 ] || ahead="$(git -C "$1" log --branches --not --remotes --oneline | wc -l | tr -d ' ')"
  dirty="$(git -C "$1" status --porcelain --untracked-files=normal | wc -l | tr -d ' ')"
  untracked="$(git -C "$1" ls-files -o --exclude-standard | wc -l | tr -d ' ')"
}
# Every repo with a branch is bundled: a remote the reset wipes (the estate's own Gitea) or a stale
# remote-tracking ref looks "pushed" and is not there when germinate runs (review 11-03).
needs_bundle() { [ "$branches" != 0 ]; }
# Linked worktrees of repo $1 (the main one, always first, is skipped): path TAB sha TAB branch TAB prunable
wt_scan() {
  git -C "$1" worktree list --porcelain | awk '
    function out() { if (p != "" && n > 1) print p "\t" s "\t" b "\t" x }
    /^worktree /{ out(); n++; p = substr($0, 10); s = ""; b = ""; x = 0; next }
    /^HEAD /{ s = $2 } /^branch refs\/heads\//{ b = substr($0, 19) } /^prunable/{ x = 1 }
    END { out() }'
}
# A detached commit travels only if a local branch holds it (the bundle and the heads carry branches).
held() { [ -n "$(git -C "$1" for-each-ref --contains "$2" refs/heads)" ]; }

echo "== repos under ${PROJECTS/#$HOME/~} and the estate"
repos=() changes=() lost=()
for g in "$PROJECTS"/*/.git "$EST/.git"; do
  [ -e "$g" ] || continue
  r="$(dirname "$g")"
  repo_facts "$r"
  if [ -f "$g" ]; then
    # A linked worktree: recreated from its main repo's record; only its local changes travel here.
    [ "$dirty" = 0 ] || changes+=("$r")
    printf '  %-6s %-28s worktree, local-changes=%s\n' "$([ "$dirty" = 0 ] && echo ok || echo CARRY)" "$(basename "$r")" "$dirty"
    continue
  fi
  repos+=("$r")
  [ "$dirty" = 0 ] || changes+=("$r")
  if needs_bundle; then tag=CARRY; add_kb "$r/.git/objects"; elif [ "$dirty" != 0 ]; then tag=CARRY; else tag=ok; fi
  printf '  %-6s %-28s branches=%s remotes=%s unpushed-commits=%s local-changes=%s\n' "$tag" "$(basename "$r")" "$branches" "$remotes" "$ahead" "$dirty"
  if [ "$branches" != 0 ] && ! git -C "$r" symbolic-ref -q HEAD >/dev/null && ! held "$r" HEAD; then
    lost+=("${r/#$HOME/~}: detached HEAD $(git -C "$r" rev-parse --short HEAD) is on no branch"); echo "  LOST   ${lost[${#lost[@]}-1]}"
  fi
  nwt=0
  while IFS=$'\t' read -r wt sha br prn; do
    if [ "$prn" = 1 ]; then echo "         gone   ${wt/#$HOME/~} (prunable: its directory is missing; not recreated)"; continue; fi
    wdirty="$(git -C "$wt" status --porcelain | wc -l | tr -d ' ')"
    case "$wt/" in
      "$HOME"/*) nwt=$((nwt + 1)) ;;
      *) [ "$wdirty" = 0 ] && { echo "         skip   $wt (outside \$HOME; its commits ride the repo)"; continue; }
         lost+=("$wt: outside \$HOME with $wdirty uncommitted change(s)"); echo "  LOST   ${lost[${#lost[@]}-1]}"; continue ;;
    esac
    if [ -z "$br" ] && ! held "$r" "$sha"; then
      lost+=("${wt/#$HOME/~}: detached at ${sha:0:12}, a commit no branch holds"); echo "  LOST   ${lost[${#lost[@]}-1]}"
    fi
    # A worktree directly under the projects dir has its own row above, which carries its changes.
    [ "$(dirname "$wt")" = "$PROJECTS" ] || [ "$wdirty" = 0 ] || {
      lost+=("${wt/#$HOME/~}: $wdirty uncommitted change(s); commit them first"); echo "  LOST   ${lost[${#lost[@]}-1]}"; }
  done < <(wt_scan "$r")
  [ "$nwt" = 0 ] || echo "         $nwt worktree(s) recorded, recreated by germinate"
done
# A directory under the projects dir that is no git repo is not carried: named, never skipped.
for d in "$PROJECTS"/*; do
  [ -e "$d/.git" ] && continue
  lost+=("${d/#$HOME/~}: not a git repo ($(du -sh "$d" 2>/dev/null | cut -f1)), not carried"); echo "  LOST   ${lost[${#lost[@]}-1]}"
done
for r in ${changes[@]+"${changes[@]}"}; do
  kb=$((kb + $( (cd "$r" && git ls-files -o --exclude-standard -z | xargs -0 stat -f %z | awk '{s += $1} END {print int(s / 1024)}') )))
done

# ── 3. Service data lives in the backup: is it fresh? ──
echo "== backup (service data is restored from it, not carried here)"
# last_run is written even when a source failed: every source must have succeeded, and the last
# backup-verify (a replay of the dumps) must be green and from the last 8 days. "?…" = not fresh.
last="$(python3 "$(dirname "$0")/backup-fresh.py" 2>/dev/null || echo "?unreadable")"
repo="$(grep -E '^restic_repo:' "$EST/config.yml" 2>/dev/null | sed 's/^restic_repo: *//; s/"//g' || true)"
echo "  last backup run: ${last} h ago; restic repo: ${repo:-not set in config.yml}"
lastblank="$(tail -1 "$NOS_HOME/blank-runs.jsonl" 2>/dev/null | sed -n 's/.*"started": *"\([^"]*\)".*/\1/p')"
echo "  last blank: ${lastblank:-none recorded} (a spore sealed before it holds a secret master that no longer opens this estate)"
stale=0
if [ "${last#\?}" != "$last" ] || [ "$last" -ge 6 ]; then echo "  STALE: the last backup is older than 6 h: run the backup (and backup-verify), then seal"; stale=1; fi
case "$repo" in
  "") echo "  REFUSE: restic_repo is empty: no service data would survive the reset"; stale=1 ;;
  /*) [ -d "$repo" ] || { echo "  MISSING: the restic repo $repo is not reachable"; stale=1; } ;;
  *) echo "  (a remote repo: reachability is not checked from here)" ;;
esac

echo "== DataTables: exported into the image by tools/keap-tables.py export"
size_mb=$((kb * 2 / 1024)); [ "$size_mb" -ge 2048 ] || size_mb=2048
if [ "$CONFIRM" = 0 ]; then
  echo ""
  echo "DRY RUN: nothing written. ${missing} file(s) missing, ${#repos[@]} repo(s) recorded, ${#changes[@]} tree(s) with local changes, ${#lost[@]} LOST, backup stale=${stale}, image ${size_mb} MB."
  echo "Seal it: $0 --to $TO --confirm   (asks a new passphrase; keep it off this machine)"
  exit 0
fi
[ "$missing" = 0 ] || { echo "REFUSE: ${missing} file(s) missing; fix or say why before sealing" >&2; exit 3; }
[ "$stale" = 0 ] || { echo "REFUSE: the backup is older than 6 h, or its repo is unset or unreachable; run the backup first: a spore does not carry service data" >&2; exit 3; }
[ "${#lost[@]}" = 0 ] || [ "$ACCEPT_LOSS" = 1 ] || { echo "REFUSE: ${#lost[@]} LOST row(s) above; commit them, or pass --accept-loss to seal without them" >&2; exit 3; }

# ── Seal ──
mkdir -p "$TO"
IMG="$TO/nos-spore.sparsebundle"
[ ! -e "$IMG" ] || { echo "REFUSE: $IMG exists; move it aside (a spore is never overwritten)" >&2; exit 3; }
attached=""
detach() { hdiutil detach "$1" >/dev/null || { echo "FAILED: could not detach $1; eject it in Finder before unplugging, and treat this spore as unsealed" >&2; exit 5; }; }
trap '[ -z "$attached" ] || detach "$attached"' EXIT
echo "Creating $IMG (AES-256, ${size_mb} MB). hdiutil asks for a NEW passphrase now."
hdiutil create -size "${size_mb}m" -type SPARSEBUNDLE -fs APFS -encryption AES-256 -volname nos-spore "$IMG" >/dev/null
MNT="$(mktemp -d /tmp/nos-spore.XXXXXX)"
echo "Opening it (the same passphrase)."
hdiutil attach "$IMG" -mountpoint "$MNT" -nobrowse >/dev/null; attached="$MNT"
umask 077
mkdir -p "$MNT/nos" "$MNT/estate" "$MNT/trees" "$MNT/home" "$MNT/keap-tables"
for f in "${files[@]}"; do cp -p "$f" "$MNT/nos/"; done
for f in "${estate[@]}"; do
  rel="${f#"$EST"/}"; mkdir -p "$MNT/estate/$(dirname "$rel")"; cp -p "$f" "$MNT/estate/$rel"
done
for d in ${homedirs[@]+"${homedirs[@]}"}; do
  rel="${d#"$HOME"/}"; mkdir -p "$MNT/home/$(dirname "$rel")"; cp -Rp "$d" "$MNT/home/$rel"
done
for r in "${repos[@]}"; do
  t="$MNT/trees/${r#"$HOME"/}"; mkdir -p "$t"
  repo_facts "$r"
  git -C "$r" remote -v | awk '$3=="(fetch)"{print $1, $2}' > "$t/remotes"
  cp -p "$r/.git/config" "$t/git-config"   # hooksPath, upstreams, nos.estate-ref: germinate restores it
  git -C "$r" for-each-ref --format='%(objectname) %(refname)' refs/heads > "$t/heads"
  if b="$(git -C "$r" symbolic-ref -q --short HEAD)"; then echo "branch $b"; else echo "detached $(git -C "$r" rev-parse HEAD)"; fi > "$t/head"
  wt_scan "$r" | awk -F'\t' -v h="$HOME/" '$4 == 0 && index($1, h) == 1 {
    rel = substr($1, length(h) + 1); if ($3 != "") print "branch\t" $3 "\t" rel; else print "detached\t" $2 "\t" rel }' | sort -t "$(printf '\t')" -k3 > "$t/worktrees"
  if needs_bundle; then git -C "$r" bundle create -q "$t/repo.bundle" --branches --tags; fi
done
for r in ${changes[@]+"${changes[@]}"}; do
  t="$MNT/trees/${r#"$HOME"/}"; mkdir -p "$t"
  if git -C "$r" rev-parse -q --verify HEAD >/dev/null; then git -C "$r" diff HEAD --binary; else git -C "$r" diff --cached --binary; fi > "$t/changes.patch"
  repo_facts "$r"
  [ "$untracked" = 0 ] || (cd "$r" && git ls-files -o --exclude-standard -z | tar --null -T - -czf "$t/untracked.tgz")
done
git -C "$EST" rev-parse --abbrev-ref 'estate@{upstream}' 2>/dev/null | sed 's#^origin/##' > "$MNT/estate-ref" || echo dev > "$MNT/estate-ref"
KEAP_TABLES_BUNDLE_DIR="$MNT/keap-tables" python3 "$EST/tools/keap-tables.py" export --confirm
cp "$(dirname "$0")/germinate.sh" "$TO/germinate.sh"
shasum -a 256 "$TO/germinate.sh" | cut -d' ' -f1 > "$MNT/germinate.sha256"
{
  echo "user=$(id -un)"; echo "uid=$(id -u)"; echo "home=$HOME"; echo "arch=$(uname -m)"
  echo "macos=$(sw_vers -productVersion)"; echo "nos_commit=$(git -C "$EST" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "estate_rel=${EST#"$HOME"/}"; echo "caroot=$CAROOT"; echo "sealed=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for r in "${repos[@]}"; do
    t="$MNT/trees/${r#"$HOME"/}"
    echo "repo=${r#"$HOME"/} branches=$(wc -l < "$t/heads" | tr -d ' ') worktrees=$(wc -l < "$t/worktrees" | tr -d ' ') bundle=$([ -f "$t/repo.bundle" ] && echo yes || echo no)"
  done
  for l in ${lost[@]+"${lost[@]}"}; do echo "lost=$l"; done
} > "$MNT/HOST"
(cd "$MNT" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256)
n_files="$(wc -l < "$MNT/MANIFEST.sha256" | tr -d ' ')"
detach "$MNT"; attached=""
# Read it back from the disk, not the page cache: a fresh read-only attach (the passphrase again).
echo "Reading it back read-only (the same passphrase)."
mkdir -p "$MNT"
hdiutil attach "$IMG" -mountpoint "$MNT" -nobrowse -readonly >/dev/null; attached="$MNT"
(cd "$MNT" && shasum -a 256 -c --quiet MANIFEST.sha256) || { echo "FAILED: the image does not read back" >&2; exit 4; }
detach "$MNT"; attached=""
date -u +%Y-%m-%dT%H:%M:%SZ >> "$NOS_HOME/spore-seals.log"
echo "Sealed: $IMG (${n_files} files, read back OK, detached). On the new Mac: bash $TO/germinate.sh"
