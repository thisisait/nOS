---
id: 2026-07-18-doctrine-and-filesystem
title: "A constitution for nOS: doctrine as code, one root for the filesystem"
date: 2026-07-18
namespace: nos-core
summary: "nOS grew a constitution layer — docs/doctrine/, terse canonical decisions a contributor or agent can't guess wrong. Three files landed this cycle: filesystem (one nos_data_root, three data classes, real isolation only where UIDs are), observability (telemetry is best-effort and may NEVER slow a run), and secrets (one resolved source, no self-referential templates). Each was written the hard way — a 258 MB /tmp fallback that crawled a release blank, an HMAC secret that desynced across two resolutions, 42 scattered per-service data dirs with zero tenant/user isolation. The constitution is what makes nOS replicable and shippable, not just runnable."
tags: [doctrine, filesystem, observability, secrets, release, architecture]
actors: [pazny, claude]
related: [docs/doctrine/README.md, docs/doctrine/filesystem.md, docs/doctrine/observability.md, docs/doctrine/secrets.md, docs/archive/fs-doctrine.md]
---
## Why a home lab needs a constitution

nOS is ~50 services, 72 Ansible roles, 68 anatomy plugins, and a `blank=true`
promise: wipe everything, reinstall from scratch, get the same machine back. A
promise like that has a failure mode that doesn't show up in a single run — it
shows up on the *second* machine, the *next* contributor, the *first* agent that
edits a role by guessing at a convention. If the load-bearing decisions live only
in the heads of the people who made them, "replicable" is a wish, not a property.

So this cycle nOS grew a **constitution layer**: `docs/doctrine/`. The rule is
narrow on purpose — *if a design choice is one a future contributor or agent could
plausibly get wrong by guessing, it belongs here*. Each file is 10–80 lines of
canonical decision, not an essay; the rationale and phasing stay in `docs/plans/`
and the guides. Three files landed, and every one of them was written the hard way.

## Filesystem: one root, three classes, honest isolation

Before this cycle, persistent data was 42 scattered `~/<service>` directories with
zero structure — no tenant boundary, no per-user boundary, no place for an agent's
scratch that a tool could refuse to leave. You cannot build multi-tenant, multi-user,
or multi-agent-per-user security on top of `~/gitea` and `~/nextcloud-data`.

[`filesystem.md`](../../../doctrine/filesystem.md) fixes the shape:

- **One root.** All persistent data lives under a single absolute `nos_data_root`
  (default `~/nos`, works out of the box; point it at an SSD by setting *one*
  variable — `external-paths.yml` sets that one, not 47).
- **Three data classes, because they isolate differently.** *Platform engine* (DBs,
  indexes) is unified but not per-user — the app does multi-user internally.
  *Tenant-shared content* (Nextcloud, media, repos) is app-owned ACLs under
  `tenants/<t>/shared/<svc>/`. *FS-native per-user* (Puter files, euro-office docs,
  a personal calibre library, agent scratch) is `tenants/<t>/users/<uid>/`, where the
  **filesystem itself is the boundary**.
- **Isolation is real only on Linux.** Per-user `0700` needs distinct UIDs; macOS
  runs every container as one user, so macOS gets *structure*, Linux gets
  *isolation*. The playbook stays "real-server-ready" so class-3 `0700` is genuine
  where it matters.
- **Paths are global, derived, single-source.** Every service path is
  `{{ nos_data_root }}/<class>/<svc>/<leaf>`, defined once — not in role defaults —
  because they're read *before the owning role runs* (blank-reset, core-up
  dir-creation, and the plugin/wiring loader all touch them). A role-default-only
  value trips the eager-resolve trap and hard-fails a blank.

The payoff shows up immediately in the cortex: KEAP now ingests a self-model of
nOS's own architecture — one `dataPoint` per service under
`tenants/<t>/shared/nos-docs/`, class-2 shared, carrying each service's *real*
deployed state (version, image, port, domain) resolved from the live vars. nOS
describes itself, correctly, because the tree has a lawful home.

## Observability: it watches the system, it never gates it

The observability doctrine has a blunt origin story. The Ansible telemetry
callback signs each event with an HMAC secret and POSTs it to Bone. When that
pipeline broke, every event spilled to a SQLite fallback — in world-shared `/tmp`,
unbounded. It reached **258 MB**, an IDE's language server opened it and held a
read lock, and per-event writes started thrashing the page cache. A release blank
**crawled to a near-halt** for minutes at a time, and the log looked frozen with no
clue why.

[`observability.md`](../../../doctrine/observability.md) draws the line that should
have existed from day one: **observability is best-effort and must NEVER slow,
block, crash, or fail a run.** Concretely:

- **A circuit-breaker.** After N consecutive transport failures the emitter disables
  itself — no POST, no fallback write — with one warning. And it's *half-open*: a
  transient outage (Bone still booting early in the run) trips it, then it re-probes
  and resumes once the sink is back, so a broken 30 seconds can't kill telemetry for
  the whole run.
- **Bounded, private, fail-open.** The fallback is a ring buffer with a hard cap,
  in the `~/.nos` runtime sidecar — never `/tmp`. `4xx` is not retried (a `401` is
  not transient). A gate is loud; an emit is silent — and putting `failed_when` on
  the wrong one is the recurring mistake.

## Secrets: one resolved source, no self-reference

The same telemetry saga exposed a subtler bug: the callback and Bone were resolving
`wing_events_hmac_secret` two *different* ways, and diverging. Its play-scope value
is a self-referential template — `{{ wing_events_hmac_secret | default(bone_secret) }}` —
which resolves correctly *only* through Ansible's full variable hierarchy. A callback
that read it raw, or naively templated it against play-vars, got the wrong value and
signed everything with garbage.

[`secrets.md`](../../../doctrine/secrets.md): when a host daemon and an in-process
consumer share a secret, **both read the same already-resolved source**
(`~/.nos/secrets.yml`), never two independent resolutions; a raw-var consumer rejects
any value still containing `{{`; and a daemon that can hold a stale secret across a
failed run **self-heals** (a signed-ping self-test triggers an inline reload) rather
than waiting for the next clean run.

## What this has to do with being ready to ship

A green `failed=0` is not the same as a working platform — this cycle proved it,
painfully. A blank once reached `ok=1496` with every container healthy while
**nothing was reachable by name**: dnsmasq was configured but never *started* (the
restart handler only reloaded a plist that `brew services start` — which nothing ran
— was supposed to create). The health-wait's blindness hid it behind green. The fix
was mechanical; the lesson is the doctrine's: a gate that can ship broken silently is
worse than one that fails loud. The DNS verify is loud now.

The constitution is the difference between a machine that runs and a machine that
*replicates*. Doctrine as code — checked in, gate-pinned, terse enough to read in a
minute — is how the promise survives contact with the second machine, the next
contributor, and the first agent. That's what release-ready means here.
