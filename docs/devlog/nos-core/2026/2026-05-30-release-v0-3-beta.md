---
id: 2026-05-30-release-v0-3-beta
title: "v0.3-beta — The upgrade engine applies for real"
date: 2026-05-30
namespace: nos-core
summary: "116 commits in a week: the upgrade/coexistence engine runs its first real apply (and turns out the dry-run had been a false-positive verifier all along), Wing gains tiered RBAC from forward-auth headers via a stateless Nette identity, the orphaned Grafana SQLite datasource is found and the agent dashboards finally light up, and concurrent claude-CLI agents stop crashing each other thanks to a humble mkdir mutex."
tags: [release, upgrades, coexistence, rbac, observability, agents, grafana]
release: v0.3-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
v0.3-beta is the release of uncomfortable discoveries: machinery that had
reported green for weeks turned out to have never actually run. The week was
spent making it run — and pinning every defect the first real execution shook
loose.

## The dry-run that verified nothing

The `--tags upgrade` flow had a clean record because dry-run short-circuited
before handlers fired — it was a false-positive verifier masking a multi-defect
apply path. The first real apply found all of them at once: recipe step
strings needed Jinja2 rendering against play-vars plus engine tokens
(`nos_migrate.py` now does both namespaces); recipes said `command:` where the
exec wrapper wanted `cmd`; `compose.set_image_tag` needed `--force-recreate`
and converge-on-drift; and recipes referenced container names that don't exist
live (`<stack>-<service>-1` is the real shape).

The sharpest catch came from review, not runtime: `lookup('vars', …)` without
`wantlist=true` collapses a list of play-vars to the first character of each.
That one was found *before* a real PostgreSQL run touched it. And one doctrine
hardened into policy: Authentik major upgrades are forward-only — restoring a
pre-upgrade dump under new code half-migrates the schema, which is worse than
either direction.

Coexistence got its first stateful proof: tracks now derive from the legacy
service override (inheriting env, networks, healthcheck), and PostgreSQL 17
booted live beside 16, with major-version data moving via logical dump/restore
at cutover rather than a raw data-dir clone.

## RBAC without sessions

Wing now builds a `Nette\Security` identity from the `X-Authentik-*`
forward-auth headers on every request — stateless, so CSRF tokens survive and
no session store churns. Authentik groups become Nette roles; presenters gate
with a single declarative `$minAccessTier` property that `BasePresenter`
enforces by default, replacing the easy-to-forget per-presenter `startup()`
override. Defense-in-depth: Wing is already forward_auth Tier-1 at the edge.

## The orphaned datasource

Grafana's playbook-timeline and AI-agents dashboards had been dark for weeks
against a fully populated `wing.db`. The cause was archaeological: the P1
datasource split left the `wing_sqlite` datasource declared only in an
`all.yml.j2` that nothing rendered anymore. A new `grafana-wing` composition
plugin provisions it properly, the stub panels were rewritten against real
`agent_sessions` and `remediation_items` tables, and a CI gate now pins the
dashboard → datasource → provisioning chain so it can't silently orphan again.

Same family of bug, different vein: gitleaks 8.x dropped `--source` for a
positional repo argument, so every nightly secret scan had been exiting 2 —
the Wing Inbox and Secret Findings pages were empty because the scanner never
ran, not because there was nothing to find.

## One mkdir to rule the agents

Concurrent claude-CLI agent runs were crashing *all* participants. The fix is
the oldest trick in Unix: `pulse-run-agent.sh`, the single chokepoint every
agent run flows through, takes an atomic `mkdir` mutex — stale locks reclaimed
by PID liveness, released on any exit path. Sequential and boring, which is
exactly what an agent substrate should be.

## By the numbers

Full all-on run on the operator's host: `ok=1201 failed=0`, smoke 33/33, three
core e2e journeys green. CI-equivalent gates: pytest 1398 passed, ansible-lint
0 findings, lockfile in sync. Plus the hub autowiring epic (P1/P2): plugin
`hub_card` blocks harvested into `/hub` with tier overlays, Uptime-Kuma-backed
health, and Nextcloud↔OnlyOffice wired automatically.
