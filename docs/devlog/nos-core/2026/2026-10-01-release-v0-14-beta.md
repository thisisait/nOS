---
id: 2026-10-01-release-v0-14-beta
title: "v0.14-beta — the estate leaves cleanly, comes back, and every account is already there"
date: 2026-10-01
namespace: nos-core
summary: "82 commits after v0.13-beta. A blank, a full leave and a rebuild on this Mac found ~30 defects a converged estate had hidden; each is fixed with a gate. E2E now logs in as testers generated from the config and walks what the plugins say is wired; accounts for the admin, the operator, the tester and RBAC test users exist from install. Converged failed=0, smoke 47/47 strict, E2E 270 passed."
tags: [release, blank, leave, e2e, identities, rbac, profile-builder, backup, image-cache]
release: v0.14-beta
actors: [pazny]
related: [RELEASE.md, tools/e2e-plan.py, tools/nos-first-login.py, tools/profile-builder-build.py, tools/nos-image-cache.py]
---

`v0.13-beta` closed with the from-blank path named as unrun. `v0.14-beta` ran
it — and then ran the opposite: `nos --remove=all --confirm --leave`, an exit
audit of what stayed behind, and a rebuild on the same machine.

## Transitions, not steady state

A converged estate reports green on things that only work because of
leftovers. The blank, the leave and the rebuild found about thirty such
defects: a mkcert CA copied onto a public TLD, a Stalwart that banned its own
host, a Paperclip invite that was never created, a Woodpecker PAT that needed a
browser, a homeassistant store promoted but never restarted into, telemetry
reporting `failed=0` for a failed run, a sudo askpass file that outlived the
run, resolvers and a keychain cert a leave left behind, Homebrew 7 naming its
services `sh.brew.*` so a leave left Alloy listening. Each fix carries a gate
that went red on the broken shape first.

## Testers that come from the config

`tools/e2e-plan.py` renders every plugin's `authentik:` block and `e2e:` probes
against the resolved config — one source of truth, no hand lists. Journeys log
in as a tester per RBAC tier and prove reach and refusal; probes walk an app's
own "Sign in with Authentik" and check the effect. They found organs that a
green converge hid: a gitea compose extension dead since June (a Jinja tag in a
YAML comment), a loader that evaluated conditions without Ansible filters and
reported "degraded" silently, three plugins claiming a forward-auth gate the
edge never enforced, WordPress SSO broken for everyone (issuer, a claim
Authentik never sends, an e-mail shared with the break-glass admin), and a
loader that split container commands with `str.split()` — Nextcloud stored its
OIDC secret with the quotes.

## Accounts exist from install

`nos_identities` is the one roster. The operator is now an Authentik admin from
the first run; `tools/nos-first-login.py` signs every declared identity in to
every SSO app at the end of a converge, so accounts exist before anyone opens
an app. Apps that cannot say why (`first_login_blocked`). RBAC test users
(alice, bob, carol, dave) sit behind one toggle; live they reach exactly their
tiers and cannot read each other's Nextcloud files or Outline drafts. People
added in the profile builder get a password set once and then owned by them —
while the derivable initial one still works, every run names it.

## Also in the cut

A verified image cache a rebuild loads from (no re-pull, no rate-limit ban);
backups staged for restic/Backrest with every data dir carrying a verdict; the
profile builder v3 with a People step and a credentials.yml it actually writes;
Ollama 0.35; MIT license and a rewritten README. Jellyfin libraries mount at
their host path, and the inbox a fresh install opens to no longer carries
alarms for stores that are empty by declaration, historic gitleaks findings
already closed, or a clock firing a workflow the operator has not activated.

## Not yet

Admin rights inside apps beyond Grafana; six apps that cannot pre-create
accounts (named in their plugins); `secrets.yml` encrypted at rest (queued).
