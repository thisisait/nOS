# 60 — An estate that remembered its own setup

**Found** 2026-10-08; **open** (each defect is fixed and gated; the release
rule that would have found them is a decision).

## Green here, red on a clean machine

The first deploy on a machine that had never run nOS (2026-10-08) needed twelve
fixes, every one of them green on the maintainer's estate, which had converged
hundreds of times:

- `brew install` cap assumed GNU coreutils (`b7bc1b8b`)
- `/usr/local/bin` absent before the Docker CLI links (`c480f253`)
- `pyenv exec` honoured the repo's own `.python-version` pin (`e1aa1410`)
- a `credentials.yml` copied with its `{{ }}` templates was accepted (`dc272562`)
- the user-scope service directory did not exist yet (`f7ce8fec`)
- Homebrew 7 renamed the dnsmasq plist (`634b057f`)
- the host `node` came from nvm, not `PATH` (`84eea8b3`)
- Authentik scope mappings looked up by name, not managed id, in the role and in
  tofu (`be4ba6d4`, `e255a594`, `8751c8ba`)
- the mkcert CA was mounted but not trusted (`8d6c751e`)
- the pinned FrankenPHP was fetched on Linux only (`ff80a735`)

## The mechanism

A converged estate carries state that earlier runs left behind: a directory an
old task created, a binary from a different install path, a name an earlier
Authentik version used, a tool installed by hand once. Every later run finds it
and passes. The playbook's missing step is invisible exactly where it is tested,
because the host already remembers doing it. `--remove=data` does not clear this
either: it wipes service data, not the host's own setup (Homebrew, pyenv, nvm,
launchd dirs). A blank on the same Mac still inherits the Mac.

## When the bill comes due

On every new machine: the next client, a contributor's fork, a reinstall after a
disk swap. A first impression is the deploy that fails.

## What closes it

The twelve defects: closed, each with its own gate under `tests/anatomy/`.

## What is still owed

The rule that would have caught them before a client did: a release is not
green until a converge on a machine with no nOS history passes. Whether that
becomes a MUST on the `rel-*` rows (a second Mac, a fresh macOS VM, or the
Ubuntu cloud lane in [docs/cloud-e2e.md](../cloud-e2e.md)) is the operator's
decision.
