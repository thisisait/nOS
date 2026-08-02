# Per-user containers — a roadmap

> Opened 2026-08-02, **after** the v0.10-beta release lane. Nothing here starts
> before nOS/KEAP/cortex/face ship. This document exists so the PoC's measured
> numbers are not lost between now and then.
>
> Origin: the one-filesystem thread reached a point where the honest answer to
> "who may touch this user's files" stopped being a path guard and started being
> a boundary. The operator's framing — *"málokdy se stane, že na jednom stroji
> bude 50 uživatelů online"* — is what makes it affordable.

---

## What the PoC established

Measured 2026-08-01/02 on the real `lscr.io/linuxserver/code-server:4.115.0-ls332`
(1.09 GB), same bind mount, `--memory 1024m --cpus 2`, timed from `run` to the
first HTTP 302 on a published port.

| | apple/container 1.2.0 | Docker Desktop |
|---|---|---|
| image pull (cold) | 28.5 s | already local |
| **start → HTTP ready** | **2.1 s** | **2.4 s** |
| 800 small-file writes | **195 ms** | 273 ms |
| 800 small-file reads | **125 ms** | 141 ms |
| `ls -la` of 800 entries | 63 ms | **7 ms** |
| host RSS, helper procs | 71 MB (1 container) | 6 036 MB (64 containers) |

**Read the memory row carefully.** 6 GB is *one shared VM running the whole
estate*; 71 MB is four helper processes for *one* container. The marginal cost is
the same order — Docker adds ~83 MB inside an existing VM, apple ~20–26 MB host
RSS plus lazily-allocated guest memory. The difference that matters is not size,
it is that **Docker's allocation is pre-committed and apple's is not**.

Conclusions that survive scrutiny:

- **Start time is a tie.** An earlier 0.7 s figure was alpine — a floor, not a
  workload. A real image is 3× that and still fine for on-demand start.
- **Filesystem is split, not a win.** apple is ~30 % faster on bulk I/O and **9×
  slower on `stat`**. Both use virtiofs, so this is implementation, not
  mechanism. Opening a large project is stat-heavy (bad); saving is write-heavy
  (good). Neither disqualifies.
- **Nothing here argues for migrating the existing 63 containers.** apple is not
  clearly better or worse for the estate as it stands.
- **The per-user case is architectural, not benchmark-driven**: a kernel per
  user, memory that is not pre-committed, and each container separately
  addressable.

### The blocker nobody can automate

macOS gates `container`'s published ports behind the **Local Network** privacy
permission. Until a human clicks Allow, **host → container traffic is dropped
while the listener still binds** — so it presents as a broken runtime, not as a
policy. Two PoC runs recorded `TIMEOUT` for exactly this reason; the operator
identified it.

**It cannot be granted from a playbook.** Every other first-run prompt in the
estate is automatable; this one is a click, per machine. Its failure mode is the
worst available shape: *a listening port that does not answer.* Any adoption plan
carries a manual step, and the second machine must re-measure, because the prompt
will not appear again on this one.

---

## Why per-user at all

The existing model is **uid-partitioned directories** plus Bone's
realpath-in-scope guard plus Authentik tiers. It works, and `chmod` is not part
of it (see `one-filesystem-architecture.md` §1 — POSIX mode bits are decorative
under VirtioFS with every container running as a different uid).

Per-user containers change what the guard *is*: instead of one process
carefully refusing to leave a subtree, each user's tools run in a context that
has no other subtree mounted. The guard becomes a mount namespace rather than a
code path — which is the difference between a bug being a vulnerability and a bug
being a bug.

The services where this is worth paying for are the **data-sensitive, per-user**
ones: code-server (today a single shared instance, the reason it is isolated from
the VFS at all), and any future in-place editor.

## Cost, priced honestly

Per-user prices **concurrency, not headcount**. An idle user's container is
reaped and restarts in ~2 s. Ten concurrent editors is roughly 200–800 MB — a
fraction of what Docker Desktop has already pre-committed for the estate. Fifty
*registered* users with three online costs three containers.

The earlier objection that this "multiplies the estate" was overstated and is
withdrawn: it multiplies *sessions*, and lazy per-container VM allocation is
precisely the property that makes that real rather than notional.

---

## Stages

Each stage stands alone. If we stop after any of them, what shipped is still
coherent — that is the test.

| stage | what ships | still true if we stop here |
|---|---|---|
| **P-0 Lifecycle** | start-on-demand + reap-on-idle for **one** service, one user | the two unmeasured mechanisms become measured |
| **P-1 Routing** | Traefik routes `uid` → that user's container | the boundary is reachable, not just running |
| **P-2 code-server** | code-server becomes per-user, mounting only `users/{uid}` | the one service isolated from the VFS rejoins it |
| **P-3 Runtime choice** | keep Docker or adopt apple/container, decided on P-0/P-1 evidence | a decision with numbers behind it |

### P-0 — the two things the PoC did not measure

Stated as gaps in the PoC writeup and still open:

- **Lifecycle.** Nothing started or reaped a container on demand. Needs: what
  triggers a start, what proves readiness (not "the port is bound" — see the
  Local Network failure above), what reaps, and what happens to an in-flight
  request during a cold start.
- **Traefik uid-keyed routing.** Looks feasible, untried. The question is
  whether a router can be derived per user without regenerating the whole file
  provider on every login.

### P-1 — the identity dependency

**S-0 must land first.** Routing by uid requires that `uid` mean one thing across
Authentik, the VFS, and the container name. That is the identity intervention
already scoped in `one-filesystem-architecture.md` §4, canonical id
`slugifyUid(username)`. Per-user containers are a *consumer* of S-0, not a
substitute for it.

### P-3 — what would decide the runtime

Not the benchmarks; they are close enough to be a tie. The deciders:

1. Does on-demand start/reap work more cleanly under one than the other?
2. Does the Local Network permission make apple/container unshippable to a
   second machine without a documented manual step? (It does — the question is
   whether that is acceptable.)
3. Does the 9× `stat` gap bite a real editor opening a real project? Measure
   with a project, not with 800 empty files.

---

## Open questions, unranked

- Does a per-user container invalidate the SEC-02 network isolation model, or
  compose with it?
- Backup: 50 per-user containers means 50 stores or one shared store mounted
  per-user. The latter, presumably — but then the boundary is the mount, and the
  backup path must not be able to cross it either.
- What does an agent do when it needs to write into a user's tree? It has no
  session and therefore no container.
