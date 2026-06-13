---
id: 2026-06-13-sso-fleet-audit
title: "Auditing SSO across the whole fleet — three more silent failures, one false alarm"
date: 2026-06-13
namespace: nos-core
summary: "After the Nextcloud silent-failure fix, a full live audit swept all ~40 SSO-enabled services across the three buckets (native_oidc, forward_auth, header_oidc). Authentik's side was complete — a provider for every service. The service side held three more silent failures of the same class: Gitea registered against a REST endpoint that exists at no Gitea version (the real root of the 'SSO lockout' saga), Home Assistant pinned to a dead component version, and Woodpecker's gate — which on inspection turned out to be a false alarm that a fix would have made worse."
tags: [sso, authentik, audit, gitea, home-assistant, incident]
actors: [pazny, claude]
related: [tasks/stacks/authentik_service_post.yml, docs/sso-and-attribution.md]
---
One fixed Nextcloud login raised the obvious question: *what else is quietly
broken?* So the next move was a full live audit — not a code read (the
Nextcloud bug looked correct on paper), but actual probes against every
SSO-enabled service on the running box, bucket by bucket.

## The shape of the audit

nOS sorts SSO into three buckets (`docs/sso-and-attribution.md`): `native_oidc`
(the service speaks OIDC itself, either via env vars or service-side API
registration), `forward_auth` (Authentik's proxy outpost gates the route), and
`header_oidc` (the proxy injects identity headers). Each needs a different
probe:

- **forward_auth** — hit the route unauthenticated; a healthy gate 302s to
  Authentik, a broken one serves the app.
- **native_oidc env-driven** — confirm the OIDC env is present and non-empty in
  the container and the discovery endpoint resolves.
- **native_oidc API-driven** — the dangerous bucket: confirm the service-side
  registration (occ / CLI / settings API) actually landed.

The Authentik side was spotless: every service had its provider (18 clean
`nos-*` OAuth2 clients, 22 proxy providers, all outpost-bound). The OpenTofu
cutover had done its job. Every failure was downstream.

## Three real failures

**Gitea — registered against a phantom endpoint.** This is the one that
finally explains the long-running "Gitea SSO lockout, oauth2 source row
vanishes" saga. The playbook registered the Authentik source with
`POST /api/v1/admin/identity-providers` — an endpoint that **exists at no
version of Gitea**. The live 1.25.5 swagger has no such path; it never did.
Wrapped in `failed_when:false` + `no_log`, the POST 404'd in silence on every
run, and a "SSO guard" meant to catch exactly this lockout was itself querying
the same dead endpoint, so it could never see the source either. The fix:
register via the canonical `gitea admin auth add-oauth` CLI (idempotency keyed
off `gitea admin auth list`), across all three code paths, plus a secret-free
loud verify. Live result: source ID 1 registered, and the "Sign in with
Authentik" button is finally on the login page.

**Home Assistant — a dead version pin.** HA's `configuration.yaml` referenced
the `auth_oidc` HACS component, but `custom_components/` was empty. The pin was
`v0.9.0` — a tag that **no longer exists upstream** (the releases jump from
`v0.6.5-alpha` to `v1.0.0-rc1`); the download 404'd and, again behind
`failed_when:false`, vanished silently. Bumped to `v1.1.1` — which changed the
config schema (the old `automatic_user_linking`/`automatic_person_creation`
feature keys are gone and a strict schema would reject them), so the rendered
block had to change too. The fragile download→extract→move→cleanup chain (which
gated extraction on the download's `status_code`, unreliable under
`until`/retries) was rewritten as one idempotent tar step gated on the tarball
actually existing. Live result: `auth_oidc 1.1.1` installed.

## The false alarm

**Woodpecker looked like a bypass — and wasn't.** The audit flagged
`ci.pazny.eu` as serving its SPA shell unauthenticated, no forward-auth gate.
The reflex was to add the gate. That turned out to be wrong twice over: it
broke the playbook's own Woodpecker API post-wiring (every call 302'd to
Authentik), and more fundamentally it's the **double-login anti-pattern** nOS
explicitly warns against — Woodpecker already authenticates via Gitea OAuth at
the app level, so stacking an Authentik forward-auth gate on top is two logins
for no security gain. The unauthenticated SPA shell is just static JS; every
API call behind it 401s. So the "fix" was reverted, and the real lesson got
written into the auth-mode table: app-auth IS the gate here.

## What pins it now

Every silent-failure surface gained a **loud, secret-free verify** that fails
(or, for the optional HA component, warns prominently without aborting the
whole converge) when registration doesn't land — the same guard that would have
caught all four of these on day one. The `failed_when:false` + `no_log`
combination is reasonable for a secret-bearing command; the lesson is that it
must always be paired with a separate verify that reads state and shouts. Live
converge: `failed=0`, smoke green (one transient timeout aside). Remaining
thread: Portainer's OAuth state couldn't be confirmed read-only — logged for a
follow-up with an admin token.
