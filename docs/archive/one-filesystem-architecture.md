# One filesystem — the architecture decision

> Design draft, 2026-08-01. Companion to
> `one-filesystem-and-office-editing.md`, which measured the present. This one
> chooses a future. Operator direction the same day: identity inconsistency gets
> **one drastic intervention**, not per-app patches; and **in-place editing that
> saves to the original location is mandatory** — read-only and
> download-edit-upload are both refused.

---

## 0. What the requirement actually rules out

Three constraints, and each one eliminates candidates before we start liking them.

1. **In-place save (C1).** The editor writes back to the same path the file was
   opened from. No local copy, no "download, edit, re-upload".
2. **One identity.** Not a mapping table between per-app id spaces — one id.
3. **Access control the operator can reason about**, ideally the
   user/group/permission model everyone already knows.

## 1. The uncomfortable finding about chmod

The operator asked for something "compliant with Linux user/group/chmod". Before
choosing, this has to be said plainly:

**POSIX mode bits are decorative on this estate today.**

- The store lives on `/Volumes/SSD1TB` reached through **Docker Desktop's
  VirtioFS**, which remaps ownership rather than preserving it. The same
  substrate already produced a hard blocker once: `restic` inside a container
  could not read host bind mounts at all (memory
  `backrest-spike-virtiofs-blocker`), and the nightly backup could not read
  `keap.db` from the launchd context until it was moved container-side.
- Every container runs as a **different** uid — Nextcloud as `www-data` (33),
  LinuxServer images as `abc` (911), node images as `node` (1000). A mode bit
  written by one is not the mode bit another sees.
- The estate's *real* access control is not POSIX at all: it is
  **uid-partitioned directories** (`users/{uid}/…`), **Bone's realpath-in-scope
  guard**, and **Authentik tiers**. That stack works; `chmod` is not part of it.

So a design that *depends* on POSIX semantics would work on the Linux port and be
theatre on the operator's actual Mac. That is not an argument against the idea —
it is an argument for choosing a model whose enforcement is real on both.

## 2. The candidates

### O1 — POSIX tree stays the truth; Nextcloud mounts it read-write

Bone VFS remains the store. Nextcloud gets it as per-user external storage, RW.
ONLYOFFICE saves through Nextcloud straight back into the tree.

- C1: **yes** (that is what RW buys).
- Access control: uid directories + Bone's guard on one path, Nextcloud's own on
  the other. **Two enforcement models over one tree.**
- Agents: write directly, as today.
- code-server: still isolated; per-user instances or nothing.
- Cost: two writers, and Bone's guarantees do not hold on the Nextcloud path.

### O2 — RustFS becomes the only store

Everything moves to object storage.

- C1: **no, structurally.** S3 has no in-place write of a byte range and no
  filesystem. ONLYOFFICE could save via its callback into S3, so *documents*
  would work — but every ordinary tool (code-server, `grep`, a script, the
  agents) loses the filesystem it currently has.
- Access control: **S3 policies, not user/group/chmod.** This is the furthest
  candidate from the stated goal, not the closest.
- RustFS is already deployed, but as the **backup target** — a role where "no
  filesystem semantics" is a feature.

**Recorded and rejected**, because it fails C1 for everything except documents
and moves *away* from the access model the operator asked for. Worth naming
explicitly so it does not get re-proposed as "the clean answer" later.

### O3 — invert it: Nextcloud becomes the store, everything else a client

The one that got stronger the more it was checked.

- **KEAP already ingests from Nextcloud.** `NOS_CONSOLIDATE_FS_ROOTS` is
  `{{ nextcloud_data_dir }}:~/keap/inbox` — the corpus already treats Nextcloud
  as a source. This is not a new direction; it is the direction already half
  taken.
- **C1 is free.** The ONLYOFFICE connector is a first-class Nextcloud app: open,
  edit, save in place, with versioning and conflict handling already written.
- **Access control is the model the operator wants, and it is enforced** — users,
  groups, per-file shares, expiry. Not POSIX, but the same *shape*, and unlike
  `chmod` on VirtioFS it actually holds.
- Nextcloud also brings **versioning, trash, and sharing** — three things the
  Bone VFS would otherwise have to grow.
- face reaches it over **WebDAV** through Bone (Bone becomes a client instead of
  a store), so face's uid-pinning and the BFF boundary are unchanged.
- code-server can mount WebDAV (`rclone`/`davfs2`) — the first credible path to
  making it edit the same files as everything else.

**What it costs, stated first:**

- **Nextcloud becomes a hard dependency for the filesystem.** Today Bone is a
  host daemon with almost no failure surface; Nextcloud is a PHP app with a DB.
  When it is down, face has no files rather than degraded files.
- Bone's VFS becomes a WebDAV client — a real rewrite of a component whose
  guards (`G1` filename/UTF-8 hardening, realpath scope) were written against a
  local path.
- Agents need per-user credentials (app passwords) instead of a local write.
- WebDAV latency on many small operations.

### O4 — status quo plus mirrors

Named only to be refused: it is what exists, and it is why the same document has
three possible locations and no answer to "where does this file live".

## 3. Recommendation

**O3, staged — but the identity epic first, and separately.**

The question underneath O1-vs-O3 is not technical taste. It is: **who is the
authority on the filesystem — a small daemon we wrote, or a large application
that already implements the features being asked for?**

For a *store* (per-user partitions, ACLs, sharing, versioning, trash, in-place
document editing, a sync client), Nextcloud already is what O1 would spend a year
growing Bone into. Bone's real value is being the **uid-pinning boundary** — and
that value survives the inversion intact, because Bone stays the thing that
decides which user's files a request may touch. It just stops being the disk.

**The staging matters more than the choice**, because O3's cost is a rewrite and
the operator wants to test filesystem sync soon:

| stage | what ships | still true if we stop here |
| --- | --- | --- |
| **S-0 Identity** | one canonical id across Authentik → Nextcloud → KEAP → face | the orphan-on-blank defect is fixed, independently of any of this |
| **S-1 Mount** | O1: Nextcloud mounts the VFS tree RW, per user | **C1 works, today's tree, no rewrite** — this is the testable thing, this week |
| **S-2 Invert** | writes move to WebDAV, Nextcloud becomes the store | one store, one ACL model, code-server joins |
| **S-3 Retire** | the `n/{tenant}/users/` tree becomes Nextcloud's store, not a peer | "where does this file live" has one answer |

S-1 is O1 and **is not throwaway work**: the same mount, the same identity, the
same scan job. S-2 changes who writes, not where the bytes are. If S-2 never
happens, S-1 is still a coherent system — that is the test of an honest stage.

## 4. The identity intervention (S-0)

The operator's call: one drastic fix, not per-app patches. Concretely.

**The canonical id is the one face already derives** —
`slugifyUid(username)`, documented in `face/src/lib/security/uid.ts` as stable
precisely because Authentik's `uid` is not. It is `[a-z0-9-]`, ≤64 chars,
filesystem-safe, and already the name of every VFS directory.

Per service:

- **Nextcloud** — `user_oidc` currently keys on a hash of the OIDC subject
  (measured: `eb2dd86e…`). Map it to a stable claim instead. Existing accounts
  keep the old id: either migrate (`occ user:rename` does not exist; a real
  migration is `files:transfer-ownership` + delete) or accept that the fix takes
  effect at the next blank. **Say which, in the plan, before starting.**
- **KEAP** — already reproduces `canonicalUid` byte-for-byte (the contract is
  written down in `uid.ts`). Verify, do not assume.
- **Gitea / GitLab / others** — enumerate, do not guess. The audit that found
  this found it in one service; there is no reason to think it is the only one.

**A gate belongs here**, and it is the same rule the two audits produced: a test
that asks every service's user store for the canonical id and fails when a
service invents its own. Otherwise this gets fixed once and drifts again.

## 5. What I would build first

1. **S-0 enumeration** — for each service with a user store, what is the id and
   is it stable across a blank? A table of measured facts, not a design. Cheap,
   and it sizes the epic.
2. **S-1 on one user** — enable `files_external`, mount `documents` RW for the
   operator, scan job, open a `.docx` in ONLYOFFICE, save, and verify the bytes
   changed **in the VFS tree**. That is the end-to-end proof, and it is a day.
3. Only then decide whether S-2 is worth the rewrite — with a working system in
   hand rather than a diagram.
