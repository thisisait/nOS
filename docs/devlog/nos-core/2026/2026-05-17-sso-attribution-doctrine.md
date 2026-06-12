---
id: 2026-05-17-sso-attribution-doctrine
title: "Three kinds of SSO, one kind of truth: locking the attribution doctrine"
date: 2026-05-17
namespace: nos-core
summary: "The SSO audit collapsed a fuzzy mode zoo into a canonical trichotomy — native_oidc, header_oidc, forward_auth — and locked it with seven CI gates. The same sweep found two Wing endpoints trusting body-supplied attribution, a privilege-escalation hole that would have let an agent forge 'resolved_by: operator' into the audit trail. Both fixed; a gate now hunts the anti-pattern forever."
tags: [sso, authentik, security, doctrine]
actors: [pazny, claude]
related: [docs/sso-and-attribution.md, docs/native-sso-survey.md, tests/anatomy/test_sso_doctrine.py]
---
## Why a taxonomy needed a lockdown

By mid-May, ~20 services declared an Authentik client, and the plugin
manifests described their SSO mode with whatever label felt right at
authoring time — `oauth2`, `proxy_auth`, things in between. The blueprint's
default-expression chain accepted all of them silently. That ambiguity isn't
cosmetic: an auditor probing `GET /` on a service needs to know whether a
200 with a login page is correct behavior or a bypassed gate.

The doctrine lock reduced reality to exactly three buckets, declared as
`authentik.mode` in each plugin manifest. **native_oidc**: the service
consumes OIDC at app level — its own login page with a "Sign in with
Authentik" button, per-user identity flowing in. **header_oidc**: the
Authentik proxy outpost forwards `X-Authentik-Username` / `-Email` and the
service auto-creates the local user — true zero-click SSO. **forward_auth**:
a pure access gate; the Authentik session means "you're in" and the service
keeps no per-user state. Each mode has a defined probe signature (302 to
`auth.<tld>` vs 200 on own UI), and the 2026-05-17 audit verified all 17
installed declarers matched theirs. Anything non-canonical now fails
`test_sso_doctrine.py` at gate time.

## The hole the audit found

The attribution chain has three layers: Authentik mints the identity
(operators via OIDC session, agents via `client_credentials` JWT), the Wing
API stamps `actor_id` from the **cryptographically verified** token, and
wing.db rows carry it. The audit swept every presenter for places where
layer two was being skipped — and found two:
`GitleaksPresenter::actionResolve` and
`RemediationPresenter::actionBulkStatus` both read `resolved_by` from the
request **body**.

That's a privilege escalation in audit-trail form: any LLM agent holding a
valid bearer token could write `resolved_by: 'operator'` and the trail
would believe it. The fix is the obvious one — both endpoints now derive
attribution from `BaseApiPresenter::getActorId()` — but the structural part
is the gate: `test_no_body_supplied_attribution_anti_pattern` sweeps every
presenter for `$body['resolved_by']` / `created_by` / `approved_by` /
`reported_by` so the class of bug can't quietly return.

## The first non-operator write

The doctrine lock was also the precondition for a small ceremony with large
implications: Phase 5, `conductor-self-test-001`. With the A10 actor-audit
migration landed and the `pulse-run-agent.sh` contract in place — mint a
`client_credentials` token as `nos-conductor`, generate one
`actor_action_id` UUID, bracket the run with `agent_run_start` / `_end`
events — the conductor agent performed the first **non-operator end-to-end
write to wing.db**. Every byte it touched is attributable to a machine
identity registered in Authentik, reconstructable from a single
`WHERE actor_action_id = ?` query. That's the bar agentic access has to
clear on this platform, and now there was an existence proof.

## Where it stands

Seven gates pin the doctrine; the `nos-<slug>` client convention means any
log line resolves to exactly one Authentik client row. Honestly deferred:
domain tables like `gitleaks_findings` still attribute indirectly via
soft-FK to the backbone, and event rows are internally consistent but
unsigned — the tamper-evident layer arrived two weeks later, with the gov
compliance batch.
