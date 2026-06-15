---
id: 2026-06-15-release-v0-7-beta
title: "v0.7-beta — The converge becomes idempotent"
date: 2026-06-15
namespace: nos-core
summary: "v0.6 made OpenTofu the Authentik authority but only ever proved it on a blank. The first non-blank re-converge refused every plan: Authentik re-issues provider PKs on each converge, so the tofu state pointed at stale IDs and the destroy guard correctly fired with no single object to blame. v0.7-beta makes authentik_engine=tofu survive re-runs via a self-reconcile preflight, fixes the matching Portainer SSO false-failure (verify the unauthenticated public endpoint, not a password JWT), and lands an overnight multi-agent review — ~40 mechanical fixes, 48 staged plan docs, and a RAG-memory MVP architecture. Proven by a three-converge arc end-to-end."
tags: [release, opentofu, authentik, sso, portainer, idempotence]
release: v0.7-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
v0.6 shipped a promise: the Authentik SSO layer is declarative HCL now, applied
by OpenTofu with real state, real plans, and a destroy guard. It was validated
the honest way — a tofu-engine blank from scratch, `failed=0`. But a blank only
ever exercises the *create* path. The first time the operator ran a **second**
converge — non-blank, on a live tenant — the engine refused to apply, and kept
refusing on every re-run. v0.7-beta is the tag where the converge becomes
idempotent.

## The bug a blank can't catch

The destroy guard did exactly what it was built to do. `tofu plan` reported a
dangerous in-place flip of 18 providers' `client_id` / `external_host` — the
lookup keys baked into every consumer's OIDC config — and the guard refused
rather than silently break SSO. The question was *why* the plan wanted that.

The answer took a three-run arc to pin down. A non-blank converge refused; a
blank cleared it (`failed=0`); the very next non-blank converge refused again,
with the identical deterministic shift. So it recurred on every re-converge.
The state recorded `module.service["bookstack"]` at provider PK 53; live
Authentik had `nos-bookstack` at PK 86, and PK 53 now held a different provider
entirely. Authentik **re-issues provider PKs** across a converge, and OpenTofu
tracks each resource by that integer PK. Once the live PKs move, the state
points at the wrong objects and every plan looks like a catastrophic rename.

The instinct was to find the churner and stop it. There isn't one. Every service
provider reads back `managed: None` — no blueprint owns them, no playbook step
bulk-deletes them; the churn is an emergent artifact of state-reset plus
partial/aborted converges. There is no single line to fix.

## The fix: make the engine self-reconcile

If you can't stop the PKs from moving, make the engine converge to live anyway.
Before `tofu plan`, a **self-reconcile preflight** re-points every
`module.service[*]` resource at its current live PK. The source of truth is the
one identity Authentik *doesn't* churn: an application imports by **slug**, and
its bound `provider` field gives the live provider PK. So
`application.slug → provider` is a stable bridge from a name that never moves to
the integer that always does.

The preflight is deliberately narrow. It is **drift-conditional** — it reads the
state's recorded PK and acts only on the resources that actually drifted, a
no-op when aligned, cheap enough to run every converge. It is **identity-only**
— it re-imports the PK mapping but never touches attributes, so the plan that
runs immediately after still diffs desired-vs-live and a *genuine* config edit
still trips the destroy guard. It is **best-effort** — if it can't run, the plan
and guard remain the authoritative rails, so the worst case degrades to the old
refuse-on-drift, never a silent apply. And it **never calls `tofu apply`**: it
backs up the state, does import/state ops only, and hands a clean state to the
real plan. Three converges later — non-blank REFUSE, blank `failed=0`, non-blank
`failed=0` end-to-end — the engine is idempotent.

## The Portainer SSO false-failure

The same root mindset surfaced a second bug. The Portainer SSO verify obtained
an admin JWT (`POST /api/auth` with the admin password) to read `/api/settings`
and confirm `AuthenticationMethod == 3`. But once OAuth2 is active, Portainer's
internal admin login `422`s **by design** — OAuth is the path — so the JWT was
unobtainable and the verify false-failed the converge though SSO was perfectly
healthy, raising a scary "DRIFT — manual reset required" and "OAuth SKIPPED" on
every re-run.

The fix is to verify the right invariant. `/api/settings/public` returns
`AuthenticationMethod` **without authentication**, so the check is now
password-independent: it fails loud only when SSO is genuinely not active
(`!= 3`), never on a password it can't use. Drift detection excludes the
already-active case, the OAuth-config step is skipped when SSO is already
configured (idempotent), and a real break-glass password drift is downgraded to
an informational note with an opt-in self-heal — never a wipe of working SSO.

## The overnight review

Underneath the two headline fixes, an autonomous overnight multi-agent review
audited the platform across twelve dimensions and burned down the backlog: ~40
mechanical security/SSO/CI fixes (PostgreSQL `16.14`, Redis `requirepass`, nginx
fail-closed locations, a MariaDB secret-leak in a `no_log`), 48 review-ready plan
docs (the Darwin-27 upgrade horizon, the ansible-core 2.24 jump, `{{ vars }}`
retirement, the euro-office toggle, ISDS/eIDAS scaffolding), and a RAG-memory MVP
architecture for the embeddings substrate. One of its own changes — making the
docker-restart handlers fail loud — was reverted when the wet-test proved the
rendered restart command had never worked; the corrective fix is planned, not
rushed.

## Validation

`failed=0` on the confirm converge end-to-end and on the blank; tofu no-REFUSE
on the second converge that always refused before; Portainer SSO verified via
the public endpoint. Offline: anatomy 1474 passed, the frozen 1:1 ci-local gate
green, ansible-lint production clean, lockfile in sync. The reconcile stays
identity-only and best-effort by design — it re-aligns PKs, it does not paper
over a real config change. The plan and the guard are still the rails.
