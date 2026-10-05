---
id: 2026-10-04-release-v0-15-beta
title: "v0.15-beta — only what was declared may run, and the estate starts watching itself"
date: 2026-10-04
namespace: nos-core
summary: "117 commits after v0.14-beta. A workload allow-list (Pulse runs named binaries from declared trees, docker.sock only behind proxies, readers for undeclared daemons, image drift and Santa telemetry), the assistant session modelled as the attacker with a pre-push scorer, an immune-system doctrine, and a GIS line from ČÚZK open data to a GeoLibre atlas. A Fable pre-release review found nine defects; all are fixed with gates that went red first."
tags: [release, allow-list, security, threat-model, immune-system, gis, atlas, santa, pulse]
release: v0.15-beta
actors: [pazny]
related: [RELEASE.md, ssot/doctrine/session-threat-model.md, ssot/doctrine/immune-system.md, tools/prepush-score.py, tools/undeclared-status.py, tools/digest-status.py, tools/santa-status.py]
---

`v0.14-beta` proved the estate can leave and come back. `v0.15-beta` asks a
harder question: of everything running on this Mac, what did nOS actually
declare — and who is watching when that changes?

## Only declared workloads run

The trigger was mundane. A converge failed because a plugin's compose
extension landed before its role's base fragment, and `docker compose` refused
22 healthy iiab services over one orphan. The fix leaves the orphan out and
names it — and opened the epic behind this release: everything that runs
should be derivable from a declaration, and the rest should be red.

Pulse used to run any path under `/Users/`; it now runs named binaries and
scripts from declared trees, with an environment allow-list, and registering a
job needs a `pulse.write` scope no agent token can hold. `docker.sock` is only
reachable through per-consumer socket proxies. Three new readers report what
nobody declared: launchd jobs and listening ports (`undeclared-status`), images
that changed without a converge (`digest-status`), and executions outside the
declared trees as seen by Santa in Monitor mode (`santa-status`). On its first
run the undeclared reader found two forgotten dev servers listening on the
LAN; they were stopped.

## The assistant is the attack surface

The operator named the uncomfortable part: the AI session that builds nOS runs
as his user, with a shell and the local services. A poisoned instruction could
edit a gate together with the code it guards, plant persistence, and wait.
`ssot/doctrine/session-threat-model.md` writes that down, including the
ceiling — same-user code can rewrite any same-user check — and
`tools/prepush-score.py` now runs inside `nos-push`: deterministic signals with
file and line first, a local model's score beside them, never instead of them.
Its first real run caught the model inventing a `curl | sh`; a model scoring
zero against strong evidence now reads UNAVAILABLE. `immune-system.md` gives
every detector one contract — heartbeat, lifespan, DNA — so silence itself
becomes a signal.

## From open data to a planet

PostGIS joined the PostgreSQL pin; a monthly loader brings in ČÚZK parcels,
buildings and RÚIAN; KEAP parties' sites project into it. GeoLibre serves the
`nos-atlas` plugin at `atlas.<tenant>`: KEAP drawn as a planet, the estate as
an island of factories, refreshed hourly by a Pulse job against a published
data contract, with a catalog of keyless ČÚZK layers and martin tiles behind
the same gate. The last bug of the cut was the atlas's own service worker
hiding an expired sign-in — fixed by a worker that removes itself, served on
the one path that needs no sign-in.

## The review before the cut

A Fable review of the whole range looked for what the gates miss and found
nine things worth fixing before tagging: a Jinja scope bug that blinded the
prune guard after the `config.d/` split, eleven device-gateway security tests
deleted inside a GDPR commit, an agent-user boundary escapable through Pulse,
synthetic users retirable by any `-y`, a daemon stop acting on one-off flags,
a backup filter that could silently drop data, a wipe that could proceed
without a survivor, and a root installer reading from `/tmp`. Each is fixed
with a gate shown red against the broken state; about thirty smaller findings
are on the roadmap as `review-v015-followups`.

## Still open

Jellyfin SSO waits for the planned blank. The default config split continues
one domain at a time. The hard boundary for the session — its own user, then a
containerized core with a thin, declared host bridge — is the next epic.
