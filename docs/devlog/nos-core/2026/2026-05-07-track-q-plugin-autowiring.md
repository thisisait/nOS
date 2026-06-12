---
id: 2026-05-07-track-q-plugin-autowiring
title: "Track Q: 63 plugins later, the roles are finally just bones"
date: 2026-05-07
namespace: nos-core
summary: "Track Q moved every scrap of cross-service wiring — OIDC clients, dashboards, scrape targets, notifiers — out of 71 Ansible roles and into per-service anatomy plugins. The per-plugin authentik: block became the SSO source of truth, and the central authentik_oidc_apps list that every new service had to edit was retired to an empty stub."
tags: [anatomy, plugins, sso]
actors: [pazny, claude]
related: [docs/bones-and-wings-refactor.md, files/anatomy/docs/role-thinning-recipe.md]
---
## The problem: every role knew too much

For its first year, nOS grew the way most Ansible codebases grow: each
`pazny.<service>` role accumulated everything its service needed. Installing
Grafana meant the Grafana role also knew about Authentik (OIDC env vars in
its compose template), about Alloy (a scrape entry hardcoded in *Alloy's*
template), about the central `authentik_oidc_apps` list in
`default.config.yml`, and about three different `tasks/post.yml` API dances.

That worked at 10 services. At 50, it meant adding one service touched five
files in four owners, and removing one left wiring shrapnel everywhere. The
bones-and-wings doctrine gave the failure a name: roles are **bones** — they
should install a thing and stop. The connective tissue — **tendons** to the
anatomy (Wing UI, Pulse, audit) and **vessels** to infra (DB, Prometheus,
Loki, OIDC, notifiers) — deserved its own home, modular and removable, with
the role knowing nothing about it.

## The structural change: one plugin per service

The A6.5 proof-of-concept thinned exactly one role (Grafana) and extracted a
`grafana-base` service plugin under `files/anatomy/plugins/`. Once that
exited green, Track Q applied the same deterministic 6-step recipe
(`files/anatomy/docs/role-thinning-recipe.md`) to the rest of the body, in
seven batches ordered by blast radius: observability first (densest wiring,
no user data), then IAM, storage, comms, content, dev/CI, and the long tail.

Each batch follows the same moves: inventory the wiring with grep, draft
`files/anatomy/plugins/<service>-base/plugin.yml`, physically move the
dashboards / OIDC blocks / scrape entries / compose env fragments into the
plugin, strip the role down to `defaults/ + tasks/main.yml + compose.yml.j2 +
meta/`, then run a blank and verify byte-identical behavior.

The headline cutover is SSO. Every plugin manifest carries an `authentik:`
block declaring its provider type, slug, and RBAC tier. The plugin loader's
aggregator harvests all of them into `inputs.clients` and renders the live
Authentik blueprint from that — the D1.2/D1.3 cutover. The legacy central
`authentik_oidc_apps` list in `default.config.yml`, once the file every new
service had to edit, survives only as an empty stub for the Tier-2
apps_runner extension channel.

## Why it held

Composition plugins (the "synapses") got the cross-service cases the old
model handled worst: `grafana-prometheus` activates only when both services
are installed, so disabling either one removes the wiring with it instead of
leaving a dangling datasource. And because plugin manifests are data, the
contract is testable — the wiring-capabilities gate later grew to pin which
manifest blocks have live consumers across all of them.

## Where it stands

63 plugins live as of this entry, every Tier-1 role on the thin-role shape or
queued for it, and "adding a new Docker service" collapsed to two files: a
thin role and a `plugin.yml`. The plugin manifest went on to become the
substrate for everything that followed — notification fanout, GDPR records,
Pulse jobs, and eventually the OpenTofu Authentik registry all read from the
same blocks Track Q created.
