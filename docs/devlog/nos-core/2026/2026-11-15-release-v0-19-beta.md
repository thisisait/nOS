---
id: 2026-11-15-release-v0-19-beta
title: "v0.19-beta — the face is the endpoint, and a stronger reader closes the books"
date: 2026-11-15
namespace: nos-core
summary: "508 commits after v0.18-beta. The face moves to SvelteKit 3 and takes over Wing's apps; the medulla serves thirteen of Wing's read sets; a new Authentik application gets its tier in one converge; the night writes down what it saw. Before the cut, six Fable reviewers read 223 rows marked review against the code: 158 shipped, 19 short of their promise, 18 superseded, none unsafe."
tags: [release, face, sveltekit, medulla, authentik, tofu, roadmap, review, supply-chain, backup]
release: v0.19-beta
status: draft
actors: [pazny, claude]
related: [RELEASE.md, files/anatomy/face, files/anatomy/thalamus/medulla, tasks/tofu-authentik.yml, tasks/verify-authentik-apps.yml, roles/pazny.backup/files/backup-verify.sh, docs/hidden_fees/65-the-medulla-answers-the-edges-in-its-own-words.md]
---

`v0.19` set out to make the face the one place a person works, and to let the
night write down what it saw. Both are in. What this release will be remembered
for is the last afternoon: before anything was closed, a stronger model read
every promise against the code.

## The face, twice caught trusting too much

SvelteKit 3 hands the server only the variables a file declares. During the
migration (`391c1a74`) build and vitest stayed green while the edge hook read an
undeclared `FACE_EDGE_TOKEN` as unset and trusted every caller; a probe against the
built server found it before the land. Now `src/env.ts` declares every variable the
BFF reads and a gate holds it (`940b6efb`).

The second catch was quieter. Kit 3 no longer writes `.svelte-kit/tsconfig.json`,
and our `tsconfig.json` still extended it. Every local lane passed on a stale copy;
the image build in the operator's converge and CI's svelte-check failed on a clean
tree. The fix extends `$app/tsconfig`, moves the four server files to
`$app/env/private`, and the token-isolation gate learned the new name before it
could go vacuous (`96692b2e`, `8523c7d4`). The integrator now deletes the
generated directories before every check.

## The medulla takes Wing's reads

Thirteen read sets — Pulse, admin, audit, inbox, notifications, events, hub,
security, agent sessions, remediation, patches, pentest, scan — are answered by the
medulla behind `medulla_read_routes`, each with a parity gate replaying the same
requests at PHP and at the medulla. The intents door got its own scoped token, and
every read door refuses it (`6d787786`, `718d24cc`). On the operator host all
thirteen were switched on and answered by the medulla the same afternoon. Where the
medulla deliberately answers an edge no caller sends in its own words, fee 65 says so.

## One converge, not two

Under the tofu engine, Authentik applications were created after the blueprint that
binds their RBAC tier: a new application stayed open to every signed-in user until a
second converge. Blueprint 20 is now re-applied right after `tofu apply`, and verify
reads the bindings back under both engines (`2946b90d`, `01c3a91c`). On the operator
host: "20 declared tier binding(s), every one held."

## The books, read before they were closed

223 roadmap rows sat in `review` — landed, waiting for a verdict. A probe per row
would have proved one fact each. Instead six Fable reviewers took about forty rows
apiece and read each row's promise against the commits and the code on dev, with
read-only readers where the estate could answer. The verdicts: 158 shipped, 18
superseded (dropped, after the one row whose successor lacked two requirements had
them folded in), 19 partial — each with a child row naming exactly what is missing —
and 28 that only the running estate can prove. No security flag. The partial list is
the honest part: a scrubber that hides tokens but not PEM key blocks, a system-table
filter built on the access grade the row forbade, a macOS lane still allowed to fail.

## Smaller things that will matter

- FrankenPHP is pinned to our own attested mirror; the re-pin tool now refuses a
  build of `main` attested by the right signer (`ba8fcca0`, `5651f27e`).
- PostgreSQL 16.16, n8n 2.47.7, Traefik v3.7.18 and Woodpecker v3.19.0: no
  unjudged serious advisory at the cut.
- The restore drill stopped failing every night on PostGIS's own table.
- A test's server never outlives the test; worktrees are removed only through the
  shipped pruner, after an ad-hoc cleanup deleted nested ones.

## The blank on 2026-11-15

PENDING — written from `~/.nos/blank-runs.jsonl` after tonight's
`nos --remove=data --confirm`.
