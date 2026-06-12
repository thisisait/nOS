---
id: 2026-06-06-release-v0-5-beta
title: "v0.5-beta — Honest SSO, explicit MFA, and a forged header"
date: 2026-06-06
namespace: nos-core
summary: "No new services — this tag changes how the existing fleet authenticates. Autologin coverage is documented exactly where upstream allows it (and where it can't), MFA posture becomes an explicit per-tenant choice, and three security findings the SSO work surfaced get closed and live-verified: a forgeable identity-header trust boundary (SEC-02), an n8n SSRF whose queued fix turned out to be a non-existent env var, and a Django multi-table-inheritance collision in Authentik provider flips."
tags: [release, sso, mfa, authentik, security, networking, traefik]
release: v0.5-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
The promise of one SSO across ~50 services is easy to make and hard to make
*honest*. v0.5-beta is the honesty pass: every service's login UX is now
stated as exactly what its upstream supports, the MFA posture is an explicit
config rather than an accident of flow ordering, and the act of auditing the
trust boundaries found three real holes.

## Autologin — promising only what upstream delivers

The target UX is "it feels like one app": authenticate with Authentik once,
then every subdomain is zero-to-one click. The release documents four honest
tiers instead of one false promise: **0-click** for forward_auth passthrough
(the Authentik session *is* the auth) and for native OIDC with forced redirect
(Grafana); **1-click** for the many services with an OIDC button but no
auto-redirect; and **gate + own login** as a documented ceiling — Portainer
won't auto-redirect, Infisical CE locks org-OIDC behind an enterprise license,
Metabase OSS has no OIDC at all. The ceilings are gate-enforced in the plugin
`supports:` truth so they can't be silently over-promised, and the global
force-OIDC mechanism ships dormant (`sso_autologin: false`) pending the
per-service rollout.

## MFA posture — a dial, not a mood

Non-gov default is posture B: global MFA, remembered for `hours=8`, so an
enrolled user re-challenges once a workday, not every login. The gov profile
pins strict step-up — `seconds=0`, 2FA on every authentication-flow run, no
remembered devices. In both postures MFA is configure-not-deny: an un-enrolled
user is walked through inline enrollment, never locked out.

## SEC-02 — the header anyone could forge

The juiciest find: calibre-web, 2FAuth and Firefly trust the forwarded
`X-authentik-*` / `REMOTE_USER` identity header with **zero validation**. On
the flat `shared_net`, that meant any peer container — say, a compromised n8n
— could skip Traefik entirely, talk to the backend directly, and *be anyone*
by setting one header. The fix is topological, not cryptographic: the
header-trusting backends move onto Traefik-only networks (`gated_net`,
`gated_b2b_net` with the databases joined for reach) and leave `shared_net`;
Firefly's `TRUSTED_PROXIES` narrows from `**` to `172.16.0.0/12`. Live-verified
both ways: an n8n→backend forge is unreachable (rc=1) while the edge still
serves its 302→auth. Pinned by `tests/anatomy/test_sec02_*`.

## Two smaller cuts with good stories

- **REM-043, the n8n SSRF** — the remediation queue had prescribed
  `N8N_WEBHOOK_AUTH=true` for months. That env var **does not exist**. The
  real guard is n8n's built-in `N8N_SSRF_PROTECTION_ENABLED` (in core since
  2.12, shipping default-OFF), now enabled via the plugin compose-extension.
  Lesson logged: verify a queued remediation against upstream before trusting
  it.
- **The MTI provider flip** — Authentik's `ProxyProvider` is a Django
  multi-table-inheritance subclass of `OAuth2Provider`, sharing the base PK
  and the globally-unique provider name. Flip a service from native_oidc to
  forward_auth (Infisical, per its CE ceiling) and the stale `OAuth2Provider`
  row collides with the new proxy provider — live symptom: Infisical 404 at
  the edge. `main.yml` now deletes the stale row idempotently before
  blueprints re-apply.

## The release push fought back

Shipping this tag detonated a 21-cycle CI saga worth its own scar: Integration
jobs failed with cascading "No filter named 'bool'" errors that no dev box
could reproduce. The cause was a GitHub-runner-only load path importing a
symbol that exists only in ansible-core **2.21** — the fix was a *newer*
ansible in an isolated venv, not an older pin, and the lasting artifact is the
frozen 1:1 toolchain (`tools/ci-local.sh` + `requirements.lock.yml`) that
reproduces CI's exact environment locally before any future release push.

## Validation

SEC-02 forge blocked live; Firefly healthy on its new networks; a non-gov,
non-`+all` run behaviourally unchanged except the network-isolation move.
Bonus autowiring: Calibre-Web bootstraps an empty library and seeds a Project
Gutenberg sample book, so the first visit isn't a blank shelf.
