---
id: 2026-05-15-release-v0-1-beta
title: "v0.1-beta — The anatomy takes shape"
date: 2026-05-15
namespace: nos-core
summary: "The first public tag of nOS: a fork of mac-dev-playbook grows a structural skeleton — the anatomy (Bone, Wing, Pulse), 63 autowiring plugins that replace central SSO config, the AgentKit audit-first agent runtime, and a role-thinning doctrine that moves cross-service wiring out of roles and into declarative plugin manifests. One command, one blank run, ~50 self-hosted services behind one SSO."
tags: [release, anatomy, agentkit, plugins, authentik, sso]
release: v0.1-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
Every project has a tag where the shape finally stops moving. For nOS that is
v0.1-beta: the point where a forked Mac provisioning playbook stopped being a
pile of roles and became a platform with a skeleton.

## The anatomy — naming the structure so it can be operated on

The core decision of this release period was a metaphor that turned out to be
load-bearing. nOS is wired as an **anatomy**: **Bone** (a local FastAPI bridge
between Ansible runs and SQLite state), **Wing** (a Nette PHP dashboard and
state-framework UI, run as a FrankenPHP launchd daemon — no sidecar container),
and **Pulse** (the host-side scheduled-job runner). Veins carry telemetry
between them; tendons are the cross-service wiring each plugin declares.

The metaphor isn't decoration. It dictates the commit style — name the exact
tendon touched, the symptom, the structural fix, and the test that pins it —
and it gave the migration framework a home: custom modules (`nos_state`,
`nos_migrate`, `nos_coexistence`), one-shot migrations with
detect/action/verify/rollback steps, and a telemetry callback that streams
every task into Wing's SQLite.

## Track Q — 63 plugins replace the central SSO list

Before this tag, adding a service to SSO meant editing a central
`authentik_oidc_apps` list in `default.config.yml` — a god-file that grew with
every service and knew too much. Track Q inverted it: each service ships a
`files/anatomy/plugins/<svc>-base/plugin.yml` whose `authentik:` block declares
its own OIDC client, tier, and auth mode. An aggregator harvests all 63 blocks
and renders the live Authentik blueprint. The central list survives only as an
empty stub for Tier-2 apps.

The companion doctrine, **D2 role-thinning**, moved OIDC env vars, mkcert CA
mounts, and `extra_hosts` out of role compose templates into plugin
compose-extensions — so a role describes the service, and the plugin describes
how the service joins the platform. A whole run of `refactor(<svc>): thin role`
commits made that real, one tendon at a time.

## AgentKit — an audit-first agent runtime in PHP

A14 shipped a self-hosted agent runtime under `App\AgentKit\*`: agents defined
as `agent.yml` + `system.md` + `rubric.md`, sessions and threads in `wing.db`,
a two-method `LLMClient` protocol so Anthropic and local OpenClaw adapters are
interchangeable via one URI string. Every LLM call lands as an events row, an
OTel span, and a token tally — `actor_action_id` lets a single SELECT
reconstruct an entire run. The follow-ups that were "deferred" lasted about a
week before shipping anyway: a multi-agent process pool, Dreams (cross-session
memory consolidation), operator-trigger UI, and webhook auto-fan-out. A
post-A14 security review caught the obvious hole — an ungated
`AgentsPresenter::actionStart` — and an RBAC gate pinned it.

## Hardening on the way to the tag

The blank-run grind closed real defects: the plugin loader now refuses unsafe
destructive paths in `remove_dir`/`remove_file`; DB connection URIs URL-encode
passwords (special characters in a generated password had silently broken
DSNs); Infisical gained CLI-driven org/project/secret seeding plus a KMS
root-key self-heal on decrypt failure; and SnappyMail joined as a Tier-1
webmail role for Stalwart.

## By the numbers

63 plugins loaded clean by the plugin-loader smoke run; 71 roles under the
`pazny.*` namespace; 8 Docker compose stacks; one `blank=true` run from an
empty Mac to a working SSO'd platform. Everything after this tag is iteration
— the skeleton holds.
