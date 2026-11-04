# Spore rehearsal (no wipe)

Prove a spore grows back before trusting it with a factory reset. Seal the spore again after every
blank and right before the reset: a blank re-mints the secret master, so a spore sealed before it
carries a key that opens nothing the reinstalled estate holds (rehearsal 11-04). Run these commands
in bash, or call `/usr/bin/find`: an interactive shell may alias `find` (fd), which broke step 4. Every write goes under
two rehearsal paths on the external disk; the live estate is only read.

1. **Fresh backup.** Run the backup (and `backup-verify`); `nos-spore.sh` refuses to seal
   when `~/.nos/backup-status.json` is 6 h old or more.
2. **Dry run.** `tools/spore/nos-spore.sh --to /Volumes/SSD1TB/nos-spore-rehearsal`. Read
   every `MISSING`, `STALE` and `LOST` row; commit the LOST worktrees, or plan to pass `--accept-loss`.
3. **Seal** with a throwaway passphrase (never the real one):
   `tools/spore/nos-spore.sh --to /Volumes/SSD1TB/nos-spore-rehearsal --confirm`.
   It ends detached, after a read-only re-attach that verified `MANIFEST.sha256`.
4. **Read it yourself:**
   ```bash
   M=$(mktemp -d); hdiutil attach /Volumes/SSD1TB/nos-spore-rehearsal/nos-spore.sparsebundle -mountpoint "$M" -nobrowse -readonly
   (cd "$M" && shasum -a 256 -c --quiet MANIFEST.sha256) && echo manifest-ok
   cat "$M/HOST"
   for b in $(/usr/bin/find "$M/trees" -name repo.bundle); do git bundle verify -q "$b" || echo "BAD $b"; done
   # every bundled branch matches the live repo (no output = equal)
   for b in $(/usr/bin/find "$M/trees" -name repo.bundle); do r="$HOME/${b#$M/trees/}"; r="${r%/repo.bundle}"
     [ "$r" = "$HOME/.nos/estate" ] || diff <(git bundle list-heads "$b" | grep refs/heads/ | sort) \
       <(git -C "$r" for-each-ref --format='%(objectname) %(refname)' refs/heads | sort) || echo "DIFF $r"; done
   hdiutil detach "$M"
   ```
5. **Germinate into a scratch home** (Xcode CLT and Homebrew are already present, so steps 1-2 skip).
   The scratch home is an encrypted image too: germinate writes the secrets, ~/.ssh and the OpenTofu
   state there, and the SSD is unencrypted HFS+ with ownership disabled (review 11-03).
   ```bash
   hdiutil create -size 20g -type SPARSEBUNDLE -fs APFS -encryption AES-256 -volname rehearse-home \
     /Volumes/SSD1TB/rehearse-home.sparsebundle
   R=$(mktemp -d /tmp/rehearse-home.XXXXXX)
   hdiutil attach /Volumes/SSD1TB/rehearse-home.sparsebundle -mountpoint "$R" -nobrowse
   HOME="$R" bash /Volumes/SSD1TB/nos-spore-rehearsal/germinate.sh --confirm
   ```
   Stop it before the bootstrap step if it reaches the network you do not want touched.
6. **Diff** the grown tree against the live one:
   ```bash
   # R is still the mounted scratch home from step 5
   for f in secrets.yml identity-map.yml state.yml; do cmp ~/.nos/$f $R/.nos/$f; done
   cmp ~/.nos/estate/config.yml $R/.nos/estate/config.yml
   grep -n "$HOME" $R/.nos/nos-cli.env   # expect no hit: every old path was rewritten
   for r in ~/projects/*/; do n=$(basename "$r"); [ -d "$R/projects/$n/.git" ] || continue
     diff <(git -C "$r" for-each-ref --format='%(objectname) %(refname)' refs/heads) \
          <(git -C "$R/projects/$n" for-each-ref --format='%(objectname) %(refname)' refs/heads) >/dev/null || echo "DIFF $n"
     [ "$(git -C "$r" rev-parse HEAD)" = "$(git -C "$R/projects/$n" rev-parse HEAD)" ] || echo "HEAD $n"; done
   ```
   Re-run step 5 once: every line must say `in place` (resumable), and nothing may be overwritten.
7. **Clean up only the rehearsal paths**:
   ```bash
   hdiutil detach "$R"
   rm -rf /Volumes/SSD1TB/nos-spore-rehearsal /Volumes/SSD1TB/rehearse-home.sparsebundle
   ```
   Worktrees grown under the scratch home are registered only in the scratch repos, so the live
   repos hold no entry for them.
