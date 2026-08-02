# 04 — One filesystem

**Status: measured, not built. S-0 identity is half-done — fixed forward, legacy
account still live.**
**Detail:** [`one-filesystem-architecture.md`](../archive/one-filesystem-architecture.md) ·
[`one-filesystem-and-office-editing.md`](../archive/one-filesystem-and-office-editing.md) ·
[`s0-identity-and-fs-core-candidates.md`](../archive/s0-identity-and-fs-core-candidates.md) ·
[`fs-doctrine.md`](../archive/fs-doctrine.md)

## The problem

The same document can live in three disjoint roots — the Bone VFS tree,
Nextcloud, and a service's own volume — and nothing decides which is real. There
is no answer to *"where does this file live"*.

## The uncomfortable finding

**POSIX mode bits are decorative on this estate.**

VirtioFS remaps ownership rather than preserving it, and every container runs as
a different uid — Nextcloud `www-data` (33), LinuxServer images `abc` (911), node
images `node` (1000). A mode bit written by one is not the mode bit another sees.

The estate's *real* access control is uid-partitioned directories, Bone's
realpath-in-scope guard, and Authentik tiers. A design that depends on `chmod`
would work on the Linux port and be theatre on the operator's Mac.

## Three architectures, one rejected on the record

- **O1 — POSIX tree stays the truth, Nextcloud mounts it RW.** In-place save
  works; two enforcement models over one tree.
- **O2 — everything moves to RustFS.** **Rejected.** S3 has no in-place byte
  write and no filesystem; documents would work and every ordinary tool
  (`grep`, code-server, the agents) would lose the filesystem it has. It is the
  *furthest* candidate from the stated access model, not the closest — recorded
  explicitly so it is not re-proposed as "the clean answer".
- **O3 — invert it: Nextcloud becomes the store.** Strongest on inspection; KEAP
  already ingests from it. Costs a Bone rewrite and makes a PHP app a hard
  dependency for the filesystem.

**Recommendation: O3 staged, but S-0 first and separately.** S-1 (O1) is not
throwaway — same mount, same identity, same scan job.

## S-0 — one identity, half-landed

Nextcloud was the single service keying accounts on a **hash** of the canonical
uid. The subtle part: `mapping-uid` was already `preferred_username`, so the
config read correctly — the hashing comes from a *second* setting, `uniqueUid`,
layered on top.

`--unique-uid=0` on both provider paths, plus a read-back that verifies the
**effect** (a 64-hex id is a hash whatever the provider table claims).

**Honest scope: this fixes the next login.** The existing hashed account
`eb2dd86e…` is live, unmigrated, and the converge names it by hand. Moving it
needs `occ files:transfer-ownership` before any deletion.

## Next

**S-1 on one user, one day of work:** enable `files_external` (shipped but
**disabled**), mount `documents` RW, scan job, open a `.docx` in ONLYOFFICE,
save, and verify the bytes changed **in the VFS tree**. That is the end-to-end
proof; everything above is argument until it passes.
