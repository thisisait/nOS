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

## 1b. Corrections from the deeper pass, measured

Two claims in the first draft were checked against the live estate. One was
wrong, and the other turned out to be bigger than a caveat.

### `files_external` is shipped but **DISABLED**

`occ app:list` lists it under `Disabled:`, and the `files_external` command
namespace does not exist until it is enabled — `occ files_external:list` answers
*"There are no commands defined in the files_external namespace."* The design
survives (one `occ app:enable files_external`), but the provisioning task must
enable it and **read back** that the namespace answers, rather than assume.

### The uid mismatch is real, and it is bigger than this feature

Measured on the live Nextcloud:

```
user_id      eb2dd86eab913e84f0d2e198af6c9c64af4e3b159d8b0eea2768a95bdd77ebf8
display_name nOS Admin
email        admin@pazny.eu
```

Nextcloud's `user_oidc` keys the account on a **hash of the OIDC subject**. face
does the opposite on purpose: `src/lib/security/uid.ts` records that
`X-Authentik-uid` "is a RANDOM hash regenerated whenever the user is
re-provisioned — e.g. every blank wipes Authentik's DB, so the same person logs
back in under a NEW uid", and therefore derives a **stable slug from the
username**: `slugifyUid('Pázny') → 'pazny'`.

The two identities differ **by construction**, and Nextcloud uses precisely the
unstable kind face rejected. Two consequences:

1. A per-user mount cannot be provisioned by "use the uid" — there is no single
   uid. Something has to map one to the other, or they have to be made one.
2. **Nextcloud carries the orphan-on-blank defect face already fixed.** Its user
   id derives from a value a blank regenerates, so after a blank the same person
   is a new Nextcloud user and the old files are orphaned under the old hash —
   the failure `blank-uninstall-managed-resources.md` §2c describes. **That is
   true today, with or without this feature.**

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

**`files_external` ships with the live Nextcloud (`1.25.1`) — but it is DISABLED**
(see §1b). Enabling it is one `occ app:enable`; it is a step, not a given.

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
- **uid ↔ Nextcloud username are NOT the same string** — verified, not assumed;
  see §1b. This is decision B below, and it is the load-bearing one.
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

## 5. The three architectural decisions, explained

These were posed as one-line questions and that was not enough to decide on.
Here is what each one actually trades, with what the research settled.

### Decision A — how does Nextcloud learn about a file it did not write?

**The problem.** An agent, or face, writes `report.docx` into the VFS. Nextcloud
did not do the write, so its file cache does not know the file exists. Until
something tells it, the file is invisible in the Files UI — and therefore
un-openable in ONLYOFFICE.

**What the research settled.** Local external storage has no inotify. Nextcloud's
own admin manual is explicit: for non-SMB storages, *"set up a cron job to
periodically rescan the external storage using `occ files_external:scan
<mount_id>`, with a typical interval of 15 minutes to balance freshness and
server load."* There is also a global `filesystem_check_changes` setting: `0`
(the default, and what this estate runs) never checks; `1` checks on every direct
access — fresher, and it costs a `stat` on every directory listing.

**The three options:**

| | freshness | cost | fails how |
| --- | --- | --- | --- |
| **A1 periodic scan** (Pulse job, 15 min) | up to 15 min stale | one scan per interval, whether or not anything changed | a file written at 12:01 is invisible until 12:15 — the operator thinks the write failed |
| **A2 `filesystem_check_changes = 1`** | immediate on access | a stat per listing, on VirtioFS, forever | slow browsing everywhere in Nextcloud, not just on this mount |
| **A3 on-demand scan** — face asks Bone/Nextcloud to scan the directory it just wrote to | immediate, targeted | one call per write | a write that bypasses face (an agent) is still invisible until something scans |

**Recommendation: A1 + A3.** The targeted scan makes the interactive path feel
instant (you wrote it, you see it), and the periodic scan is the floor that
catches every writer that is not face. A2 pays a permanent cost across the whole
of Nextcloud to fix a problem confined to one mount.

### Decision B — which identity owns the mount? (the load-bearing one)

**The problem.** `files_external:create … --user <X>` needs a Nextcloud user id.
The VFS directory is named after face's stable slug. Today those are different
strings, and Nextcloud's is unstable across a blank (§1b).

| | what it means | cost |
| --- | --- | --- |
| **B1 align Nextcloud onto the stable slug** — configure `user_oidc` to key the account on the same username-derived value face uses | one identity end to end; the mount is `--user pazny` and the directory is `users/pazny`; **Nextcloud stops orphaning its own data on a blank** | touches SSO for a live service; existing Nextcloud accounts keep the old hash id and need a migration or a re-blank |
| **B2 keep both, maintain a mapping** — a table from Nextcloud hash → face slug, consulted at provisioning | no SSO change | a second source of truth for identity, which is the exact class of defect the genome work exists to remove; and it does nothing about the orphan-on-blank |

**Recommendation: B1**, and it is worth doing *even if the office feature is
dropped*, because the orphan defect is real today. B2 buys a smaller change now
and a permanent mapping to maintain.

### Decision C — may Nextcloud write into the VFS?

**The problem.** If the mount is read-write, two systems write the same tree:
Bone (with its realpath-in-scope guard, uid pinning and filename hardening) and
Nextcloud (with its own rules). If it is read-only, ONLYOFFICE can open a
document but cannot save it — "otevírání" works, "editace" does not.

| | what you get | what you give up |
| --- | --- | --- |
| **C1 read-write** | real editing: ONLYOFFICE saves through Nextcloud straight into the VFS, author correct | two writers on one tree. Bone's guards are bypassed on the Nextcloud path, so the invariants Bone enforces (`G1` filename/UTF-8 hardening, realpath scope) must be re-established or accepted as not applying |
| **C2 read-only** | one writer (Bone), every invariant holds, no new failure mode | view-only. The stated goal — "otevírání a editaci" — is half met |

**Recommendation: start C2, and treat C1 as a separate decision with its own
verification.** It matches the operator's own sequencing ("začneme otevřením v
nové záložce"), it is reversible, and it lets the mount + scan + identity work be
proven before a second writer is introduced. Moving to C1 later is a config
change on one mount, not a redesign.

**The dependency worth naming:** C1 without B1 is the worst cell in the matrix —
a second writer whose identity is unstable across a blank.

## 6. Is this an organelle, and what does it declare?

Yes, and naming it that is not decoration — it is what stops this becoming six
hand-wired tasks nobody can reconcile later.

An `office-bridge-base` plugin declares:

- **`requires.plugin`**: `nextcloud-base`, `onlyoffice-base` — the bridge is
  meaningless without both, and the loader's DAG already refuses a plugin whose
  requirement is absent.
- **`lifecycle`**: enable `files_external`, create the per-user mount, and
  **read back** `files_external:list --user <uid>` — the audits' rule, applied
  before the code exists rather than after an incident.
- **`pulse.jobs`**: the periodic `files_external:scan` from decision A1, with its
  interval as a declared var rather than a cron string nobody can find.
- **`notification`**: the scan job's failure at `on_high` — a scan that stops
  running is a filesystem that silently stops updating, which is exactly the
  silent class the two audits were about.
- **`gdpr`**: mandatory. The bridge gives a second service access to a user's
  documents; Article 30 wants that written down.
- **`access`**: unchanged — and stating `route: none` explicitly is what proves
  the bridge added no new surface, which was the whole reason for choosing it
  over plan B.

---

## Appendix — cortex specs: what is and is not implemented

Asked the same day, so recorded here rather than lost.

**Not all of them, and the plan says so on purpose.**
`docs/archive/cortex-s3-s4-workflow-set.md` §0 states it plainly: *"The v0.10-beta
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
