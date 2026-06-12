---
id: 2026-06-12-release-v0-6-beta
title: "v0.6-beta — OpenTofu becomes the Authentik authority"
date: 2026-06-12
namespace: nos-core
summary: "ADR-0001 Phase 1 complete: every Authentik provider, application, and outpost attachment is now declarative HCL applied by OpenTofu, replacing the imperative blueprint path for that layer. The cutover was done the hard way — a tofu-engine blank from scratch — which surfaced six structural traps (including a missing grant_types field that broke every native OIDC login while forward_auth stayed deceptively green) plus three latent AgentKit runner bugs. All nine are fixed and CI-gated."
tags: [release, opentofu, authentik, sso, agentkit, infrastructure-as-code]
release: v0.6-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
nOS's SSO wiring has been declared three different ways in its short life: a
central YAML list, then per-plugin manifest blocks rendered into Authentik
blueprints, and now — for the layer that matters most — **OpenTofu HCL with
real state, real plans, and a destroy guard**. v0.6-beta is the tag where
`authentik_engine: tofu` becomes the live authority.

## The ownership split

OpenTofu owns providers, applications, and outpost attachments through one
hand-authored module (`modules/nos-authentik-app`) iterated with `for_each`
over a committed, generated registry — `state/tofu-authentik-services.yml`,
regenerated from plugin and Tier-2 app-manifest `authentik:` blocks. The other
six blueprints (groups, MFA, RBAC, agents, enrollment, brand) stay imperative
by design: they're flows and policies, not a fleet of homogeneous objects.
Safety rails are non-negotiable: apply refuses any plan containing a delete,
and the engine flag is reversible.

## Six traps from doing it the hard way

The cutover was validated via Path B — a full tofu-engine blank from scratch —
precisely because a migration-in-place would have let these hide:

- **Authentik auto-applies mounted blueprints.** Gating the Ansible
  `ak apply_blueprint` call is moot if the blueprint file still renders into
  the mounted directory — Authentik applies it on its own. Under tofu, the
  legacy OIDC blueprint must render as a no-op.
- **`lookup('file')` never resolves nested Jinja** post-ansible-2.19. The
  registry bridge needed `lookup('template')`.
- **The outpost m2m race.** The outpost attachment is a read-modify-write
  *list* on one object. Default parallelism fired 20 concurrent writes; 11
  survived. `-parallelism=1` makes attachment writes serial — slower, correct.
- **Tier-2 apps missing from the registry** — the harvest only read plugin
  manifests, not `apps/*.yml`.
- **A perpetual plan diff** on `internal_host_ssl_validation` until the module
  declared the server-side default explicitly.
- **The missing `grant_types`** — the sharpest one. Authentik 2026.5.x made
  grant types an explicit ArrayField; tofu-created providers without it
  rejected *every* native_oidc login with `invalid_request` — while every
  forward_auth route stayed green, making the platform look mostly healthy.
  Now declared in the module **and** probed live by a new e2e journey that
  exercises the authorize endpoint for all 18 OIDC providers, so a regression
  can't pass smoke again.

The post-cutover punch list shipped same-day: tofu state artifacts join the
nightly encrypted backup set, disabled services are filtered out of the tfvars
(no SSO objects for `install_*: false`), and a daily plan-only drift Pulse job
watches for divergence — it never applies, it notifies.

## AgentKit runners — first contact with reality

The release sweep ran AgentKit's native trigger paths on a deployed box for
the first time (the pulse claude-CLI runtime had masked them) and found three
latent bugs: the CLI agents-root off-by-one (Nette's `%appDir%` is derived
from the bootstrap *caller*, so repo and deployed nestings disagreed — fixed
with an explicit `agentsDir` parameter), the operator-trigger 500
(`PHP_BINARY` is empty under FrankenPHP's embedded SAPI, so spawning a child
PHP needs a `WING_PHP_BIN` fallback chain), and a missing RobotLoader in the
CLI bootstrap (AgentKit keeps value objects beside their aggregates, which
PSR-4 can't autoload). Gate: `test_agentkit_runner_paths.py`.

## Validation

Tofu-engine blank `failed=0` (ok=1418, all 8 stacks healthy) → smoke 48/48 →
`tofu plan` rc=0, full parity against the live tenant → e2e SSO journeys green
including the new native_oidc authorize probe (18/18 providers) → conductor,
scout, and remediator agents complete full runs rc=0. Anatomy suite: 1225
tests. The SSO layer is now something you can `plan` before you trust.
