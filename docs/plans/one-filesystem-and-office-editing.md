# One filesystem, and how a file gets edited

> Spec draft, 2026-08-01. Supersedes the "plan B" sketch (an unauthenticated
> edge route carrying an HMAC ticket) — the investigation below found a route
> that needs **no new exposure at all**, and that answers the identity question
> the sketch could not.

---

## 0. The three questions this answers

1. Can face open a document in ONLYOFFICE without breaking SEC-02?
2. Can the author on the Nextcloud side be the real user?
3. Is there one filesystem source of truth?

The honest answer to (3) today is **no**, and that is the root of (1) and (2).

---

## 1. Measured: three roots, zero overlap

Read from the live estate 2026-08-01 (`docker inspect`, launchd env, `occ`):

| tree | path | who can see it |
| --- | --- | --- |
| **Bone VFS** — the per-user tree face and the agents write | `{NOS_DATA_ROOT}/n/{tenant}/users/{uid}/{documents,library,inbox,agents,…}` | Bone (host daemon), face via `NOS_VFS_API_URL` |
| **Nextcloud** | `{NOS_DATA_ROOT}/tenants/{tenant}/shared/nextcloud/data/` — contains `admin`, `appdata_…`, per-user hash dirs | Nextcloud only |
| **code-server** | `{NOS_DATA_ROOT}/platform/services/code_server/workspace` | code-server only |

`n/…/users/{uid}` and `tenants/…/shared/nextcloud/data` are **different subtrees
of the same disk**, with no symlink between them. Nothing syncs them. KEAP's
`NOS_CONSOLIDATE_FS_ROOTS` reads the Nextcloud dir into the corpus, but that is a
one-way ingest into a knowledge index — not a file mirror.

**So the operator's suspicion about code-server is exactly right, and understates
it:** code-server can only edit its own workspace, and so can Nextcloud, and so
can face. Three editors, three disjoint worlds.

## 2. Why the obvious route was wrong

ONLYOFFICE does not open a URL. It needs an editor page carrying a config whose
`document.url` is fetched **by the document server container**, not by the
browser (confirmed against the ONLYOFFICE API docs; a JWT is required because
`onlyoffice_jwt_enabled: true`, and `callbackUrl` is needed only for `mode:
"edit"` — view mode does not need one).

That container cannot fetch from face:

```
iiab-face-1        → gated_net
b2b-onlyoffice-1   → b2b_b2b_net, shared_net
```

**No shared network, and that is deliberate.** SEC-02 put the header-trust
backends on a Traefik-only `gated_net` precisely so a peer container cannot forge
`X-Authentik-*`. A live forge attempt was verified blocked. Putting face on
`shared_net`, or ONLYOFFICE on `gated_net`, undoes that.

The sketch was therefore an **unauthenticated edge route** over user files,
protected only by a short-lived HMAC ticket. It would have worked. It is also a
new anonymous surface on the estate's file store, four days after REM-144 was a
new anonymous surface on the edge, and it leaves the Nextcloud author wrong
because face's uid never reaches Nextcloud.

## 3. The route that does work

**`files_external` is installed and enabled in the live Nextcloud (`1.25.1`).**

Mount each user's VFS subtree into Nextcloud as a per-user **Local** external
storage. Then:

- the file **is** a Nextcloud file, so Nextcloud's own ONLYOFFICE connector
  supplies the config, the JWT, the callback and the save path — none of which
  face has to build or hold;
- the editing user **is** the Nextcloud user (same Authentik identity via
  `user_oidc`), so the author recorded on the file is right by construction
  rather than by a header we asserted;
- face contributes **a deep link and nothing else**;
- **no new edge route, no ticket, no network change.** face stays on
  `gated_net`; SEC-02 is untouched;
- and (3) is answered as a side effect: the Bone VFS tree becomes *the* tree, and
  Nextcloud a view onto it rather than a fourth copy.

### Shape

```
Bone VFS  {NOS_DATA_ROOT}/n/{tenant}/users/{uid}/          ← THE source of truth
   │
   ├── face          reads/writes via Bone (uid pinned from forward-auth)
   ├── agents        write via Bone
   └── Nextcloud     mounts it as external storage, per user, RW
                        └── ONLYOFFICE   opens it AS that Nextcloud user
```

### The steps, and the order

1. **Bind-mount the VFS root into the Nextcloud container**, read-write, at a
   path outside `/data` (e.g. `/vfs`) so it can never be confused with
   Nextcloud's own store.
2. **Per-user external storage**, provisioned at user creation:
   `occ files_external:create "nOS" local null::null -c datadir=/vfs/{uid}` then
   `files_external:applicable --add-user {uid}` — scoped to one user, never
   global. The mount name is what the operator sees as a folder.
3. **face deep-links** into `/apps/files/?dir=…&openfile=…` (or the ONLYOFFICE
   app route once a fileId is known), opened in a new tab.
4. **A reconcile task** so a user who exists in Authentik but not yet in
   Nextcloud's external-storage table gets the mount — the same
   observe-the-effect rule the audits produced: read back
   `files_external:list --user {uid}` and fail loud if the mount is absent,
   rather than trusting the create.

## 4. What this does not solve, stated before it bites

- **Nextcloud does not see out-of-band writes until it scans.** A file the agents
  drop into the VFS appears in Nextcloud after `occ files:scan --path …`. Local
  external storage has no inotify. Either a Pulse job scans the changed subtree,
  or the operator refreshes and waits. **This is the honest cost of the design**
  and it must be measured, not assumed away.
- **uid ↔ Nextcloud username must be the same string.** They come from the same
  Authentik identity, but that is an assumption to *verify* on a live user before
  building on it.
- **VirtioFS.** A large per-user tree mounted into a container on macOS is the
  same substrate that made `restic`-in-container unusable (memory
  `backrest-spike-virtiofs-blocker`). Scan performance is a real risk to measure
  at step 1, not at step 4.
- **code-server stays isolated, and mounting the VFS into it does NOT fix that.**
  It is ONE container behind a forward-auth gate — a single workspace with no
  per-user partition. Mounting every user's tree there would hand any operator
  who can reach it every user's files, which is precisely the partition the VFS
  exists to enforce. Making code-server a real per-user editor needs per-user
  instances (or a different tool). **Until then it is an operator tool over its
  own workspace, and the docs should say so instead of implying it edits "the"
  filesystem.**

## 5. Open decisions for the operator

1. **Scan cadence** — a Pulse job on a fixed cadence, or on-demand from face when
   a directory is opened? On-demand is fresher and costs a round-trip.
2. **Mount scope** — the whole user tree, or only `documents`? Narrow is safer
   and hides `agents/` from the Files UI.
3. **Does the operator want the Nextcloud folder writable from the Nextcloud
   side?** RW makes it a real editor; RO makes Nextcloud a viewer and keeps every
   write going through Bone (one writer, simpler invariants).

---

## Appendix — cortex specs: what is and is not implemented

Asked the same day, so recorded here rather than lost.

**Not all of them, and the plan says so on purpose.**
`docs/plans/cortex-s3-s4-workflow-set.md` §0 states it plainly: *"The v0.10-beta
release does not require S3 or S4."*

- **S0 — Verify:** DONE 2026-07-26 (`cortex-s0-report.md`), verdict
  YES-with-amendments.
- **S1 / S2:** landed to the degree the release gate needs — the nightly diff
  agrees, parity `PINNED`, six clauses AGREE, `agreeStreak: 3`.
- **S3 (index on the gate) / S4 (readers and writers move):** **not done**, and
  not required for the tag. They are what make the organ *the* corpus instead of
  a second copy.
- **S5 (KEAP becomes data-only) / S6 (weights):** not started. The specs ledger
  keys most spec MOVES to S5, which is why eight specs are still vendored
  duplicates (`hidden_fees/11`).
- **`nos-cortex-lang-wing-executor.md`** is labelled *forward design, not built*
  in the ledger itself.

So: the cortex arc is complete **to the release gate**, not complete as a
"second brain". The workflow-set document exists specifically to stop those two
being conflated.
