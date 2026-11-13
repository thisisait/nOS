# 64 — A converged estate hides the missing step

**Found** 2026-10-08 (the first deploy on a clean machine, a client's); **closed per defect** the
same day (each fix landed with its gate); **open** as a rule: a release is green on the maintainer's
long-converged estate, which is the one machine that cannot show this class.

## The fee

Twelve steps were missing, and none of them showed on the maintainer's estate, because an earlier
run, a manual install or the OS image had already left the state each step assumed. On a clean Mac
every one failed, most of them deep into the first converge:

| # | What a clean machine lacked | Commit | Gate that landed with it |
|---|---|---|---|
| 1 | `timeout` (coreutils): the brew install cap fell away, one unreachable host held a cask 10 min | `b7bc1b8ba` | `test_brew_install_cap_needs_no_coreutils.py` |
| 2 | the pyenv version: the repo's `.python-version` (the CI pin) outranked pyenv global | `e1aa1410f` | `test_pyenv_exec_ignores_repo_pin.py` |
| 3 | `/usr/local/bin` on Apple Silicon: all four Docker CLI links failed | `c480f253c` | `test_docker_cli_link_dir_is_ensured.py` |
| 4 | a refusal of a copied, still-templated `credentials.yml`: it died ~40 min in | `dc2725623` | `test_credentials_override_has_no_templates.py` |
| 5 | `~/Library/LaunchAgents`: the first launchd plist render failed | `f7ce8fec7` | `test_platform_ensures_user_service_dir.py` |
| 6 | the Homebrew 6 plist name: Homebrew 7 ships `sh.brew.dnsmasq.plist` | `634b057fb` | `test_dnsmasq_label_follows_homebrew7.py` |
| 7 | a brew `node` on PATH: nOS installs node via nvm | `84eea8b3b` | `test_host_node_is_resolved_not_assumed.py` |
| 8 | a stock profile scope mapping found by name: `nos_roles` shares `profile`, so SSO broke in Gitea/HedgeDoc | `be4ba6d4a` | `test_scope_mapping_lookup_is_unambiguous.py` |
| 9 | the same lookup on the tofu path (`data.tf`) | `e255a594e` | the same gate, now scanning `terraform/` |
| 10 | a scoped tofu gate: #9 also moved `offline_access`, which no nOS mapping shares | `8751c8ba3` | the same gate, narrowed to shared scope names |
| 11 | trust of the mounted mkcert CA: nextcloud, bookstack, wordpress never ran update-ca-certificates | `8d6c751e2` | `test_mkcert_ca_mount_is_trusted.py` |
| 12 | the pinned FrankenPHP on macOS: the tap formula has no version selector, so every upstream release broke a fresh install | `ff80a7351` | `test_frankenphp_pin_governs_every_platform.py`, since folded into `test_wing_deploy_journey.py` (`a4720f097`) |

The cap fix itself needed one more pass six days later (`df788c807`: a watchdog that fired exited 0).

## When the bill comes due

Every first install, which is the moment a new owner decides whether nOS works at all. The
maintainer's estate never pays: it converges on top of state that no clean machine has.

## How it was found

By the first clean machine, not by a gate. Thousands of offline tests and the maintainer's green
converges passed over every one of the twelve; each needed a machine nothing had touched.

## What closes it

Per defect: closed, each with the gate in the table (red on the broken shape first). As a class:
only a clean-machine run before a release shows it. The blank (`nos --remove=data --confirm`) on the
maintainer's Mac is not that run: brew, pyenv, nvm, /usr/local/bin, LaunchAgents and the OS state
survive it.

## What is still owed

Whether the release checklist (rel-*) gets a MUST "a greenfield run on a second machine" is the
operator's decision; this note does not change the checklist. A clean test bed exists for Linux (the
mini); macOS has none besides a fresh user account or a reinstall.
