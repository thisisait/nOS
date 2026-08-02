# 05 — Per-user isolation

**Status: measured, queued — explicitly after the v0.10 release.**
**Detail:** [`docs/archive/per-user-container-roadmap.md`](../archive/per-user-container-roadmap.md)

## What was measured

`apple/container` 1.2.0 vs Docker Desktop, on the real
`lscr.io/linuxserver/code-server` image (1.09 GB), same mount, timed to first
HTTP 302:

| | apple/container | Docker |
|---|---|---|
| start → ready | **2.1 s** | 2.4 s |
| 800 small writes | **195 ms** | 273 ms |
| 800 small reads | **125 ms** | 141 ms |
| `ls -la` of 800 | 63 ms | **7 ms** |

**Start is a tie.** Filesystem is split: apple ~30 % faster on bulk I/O, **9×
slower on stat**. Both use virtiofs, so it is implementation, not mechanism.

**The memory figures are not the 85× they appear to be.** 6 GB is one shared VM
running the whole estate; 71 MB is four helpers for one container. Marginal cost
is the same order — the difference is that Docker's is **pre-committed** and
apple's is not.

## Why it is worth doing anyway

Not the benchmarks. The architecture: a kernel per user, memory that is not
pre-committed, and each container separately addressable. Per-user prices
**concurrency, not headcount** — an idle user's container is reaped and restarts
in ~2 s. Ten concurrent editors is a fraction of what Docker Desktop has already
pre-committed.

## The blocker no playbook can clear

macOS gates published ports behind the **Local Network** privacy permission.
Until a human clicks Allow, host → container traffic is dropped **while the
listener still binds** — it presents as a broken runtime, not a policy. Two PoC
runs recorded TIMEOUT for this reason. Any adoption carries a manual step per
machine, and the second machine must re-measure, because the prompt will not
appear again on the first.

## Order of operations, and one hard dependency

| stage | what ships |
|---|---|
| P-0 | start-on-demand + reap-on-idle for one service, one user |
| P-1 | Traefik routes `uid` → that user's container |
| P-2 | code-server becomes per-user, mounting only `users/{uid}` |
| P-3 | keep Docker or adopt apple/container, decided on P-0/P-1 evidence |

**P-1 depends on [01](01-secrets.md) P1b.** Routing by uid requires that `uid`
mean one thing across Authentik, the VFS and the container name — and the secret
scope split must exist first, or a per-user container is a full-estate
compromise. That ordering is not optional.

## Not measured

Lifecycle (nothing has started or reaped on demand) and uid-keyed routing.
Backup across N per-user stores. What an agent does when it must write into a
user's tree and has no session, therefore no container.
