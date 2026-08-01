# S-0 — one identity, and what the filesystem core should be

> Measured + researched 2026-08-01, against the live estate. Operator direction:
> identity gets one drastic intervention; the fs core may leave Docker if that
> makes the organs see each other; and this happens **now**, while nobody uses
> the system and no migration has to be written.

---

## Part 1 — S-0: the identity enumeration (measured, not designed)

Queried live: Authentik shell, `occ user:list`, `gitea admin user list`, KEAP
`/agent/v1/objects`, `wing.db`.

| service | id for the SAME human | derived from | survives a blank |
| --- | --- | --- | --- |
| **Authentik** | `akadmin` (pk `4`, `uid=ce7dfc663c77…`) | — | **username yes**; pk and `uid` **no** |
| **face / Bone VFS** | `akadmin` | `slugifyUid(username)` | **yes** — by design |
| **KEAP** | `akadmin` | username | **yes** |
| **Nextcloud** | `eb2dd86eab913e84f0d2e198af6c9c64af4e3b159d8b0eea2768a95bdd77ebf8` | **hash of** `preferred_username` | **NO** |
| **Gitea** | `pazny` | a playbook-seeded LOCAL admin — a *different account*, not the OIDC identity | n/a |
| **Wing** | `agent:devlog`, `nos-conductor`, `apps_runner` | actor strings | n/a (no human rows yet) |

### The result is better than feared

**Three of the four human-facing stores already agree on `akadmin`.** The
canonical id the face team chose — `slugifyUid(username)` — is already the
de-facto standard. There is one outlier and one adjacent problem.

### The outlier: Nextcloud, and it is a ONE-LINE fix

`provider-1-mappingUid` is **already** `preferred_username` (measured). The hash
comes from a *second* setting layered on top: `uniqueUid`, which defaults to `1`
and hashes whatever the mapping produced. `occ user_oidc:provider --help`
confirms the flag exists:

```
--unique-uid=UNIQUE-UID   Determines if unique user ids shall be used or not. 1 to enable, 0 to disable
```

So the fix is:

```bash
occ user_oidc:provider authentik --unique-uid=0
```

and Nextcloud's user id becomes `akadmin` — matching face, KEAP and Authentik.

**Existing accounts keep the old hash.** Normally that would need a migration
(`files:transfer-ownership` then delete). Per the operator's call — nobody uses
the system — **the next blank is the migration**, and that is the whole reason
to do this now rather than later.

### The adjacent problem: Gitea's parallel admin

`pazny` is not a broken mapping; it is a **second account for the same human**,
seeded locally by the playbook alongside the OIDC identity. That is a different
defect from the hash and needs its own decision (retire the local admin, or
accept it as a break-glass account and *document* it as such). Recorded here so
it is not mistaken for the same fix.

### The gate this needs

The same rule both audits produced: a check that asks each service's user store
for the canonical id and fails when a service invents its own. Without it this
is fixed once and drifts again — which is exactly how the estate got here.

---

## Part 2 — the fs core: the operator's instinct, checked

> *"klíčové apps bychom kvůli výkonu ani nemuseli mít v dockeru… orgány by tak
> na sebe lépe viděly"*

This is the strongest idea in the thread, and it is stronger than it was pitched.
Moving the filesystem core to a **host daemon** — the shape Bone, Wing and Pulse
already have — dissolves four separate problems at once:

1. **VirtioFS goes away.** Native filesystem access. The substrate that made
   `restic`-in-container unusable and forced the `keap.db` backup container-side
   simply is not in the path.
2. **POSIX ownership becomes real.** One uid — the operator's — instead of
   `www-data`(33) vs `abc`(911) vs `node`(1000) across containers. The
   user/group/chmod model the operator asked for stops being decorative.
3. **The network obstacle disappears entirely.** The whole reason ONLYOFFICE
   could not fetch from face is that `gated_net` and `shared_net` do not meet.
   A container reaching a **host** daemon has no such problem — and this estate
   already does it: `roles/pazny.face/templates/compose.yml.j2` sets
   `NOS_VFS_API_URL: http://host.docker.internal:8099/api/v1/vfs`. The pattern
   is proven, in production, today.
4. **Organs see each other over loopback** instead of through a network policy.

### Candidates, and the one constraint that separates them

The constraint is C1: **in-place editing that saves back to the original path.**

| | shape | WebDAV | OIDC | office / C1 | fits a host daemon |
| --- | --- | --- | --- | --- | --- |
| **Nextcloud** (today) | PHP + DB + container | yes | yes (hashed → fixed above) | **ONLYOFFICE connector, free, already deployed** | **no** |
| **ownCloud Infinite Scale (oCIS)** | **single Go binary, no database** | yes | yes | via **WOPI** | **yes** |
| **SFTPGo** | **single Go binary** | yes | yes (SSO) | Collabora — **licence-gated**, no official ONLYOFFICE | **yes** |
| **Seafile** | C/Python + MySQL | yes | yes | optional office integration | no |
| **RustFS / S3** | object store | no | — | **fails C1** (already rejected) | n/a |

**The fact that decides it:** ONLYOFFICE Docs has supported **WOPI since version
6.4** — we run `9.3.1.2` (euro-office fork). So oCIS can drive the document
server we already deploy, through a protocol both speak, without the Nextcloud
connector.

**SFTPGo deserves a specific note** because its Event Manager is almost exactly
the "pulse-driven organelle shots" idea: rules that fire on file operations,
provider changes or schedules, dispatching HTTP hooks and commands. If the fs
core is chosen for its *hook surface*, SFTPGo is the best of these. But its
document-editing story is Collabora under an Enterprise/on-premises licence, and
there is no official ONLYOFFICE integration — so it fails C1 on the open-core
build. Worth revisiting if C1 ever moves to Collabora.

### Where this leaves the recommendation

The previous document recommended inverting onto **Nextcloud**. That was correct
given "use what is deployed". Against the anatomy the operator is actually
describing, **oCIS is the better fit**: single Go binary, no database, host
daemon, WebDAV, OIDC, and C1 reachable through the ONLYOFFICE we already run.

**But it is not a free swap, and two things must be verified before committing:**

1. **oCIS's WOPI path needs a collaboration/WOPI service component.** It is not
   a config flag on the binary. Prove a `.docx` opens and saves through our
   existing document server *before* any of the rest is built.
2. **oCIS stores files in its own layout** (spaces, blob store), not as a plain
   POSIX tree with human-readable paths. If the "one filesystem" goal includes
   *the operator being able to `ls` it*, that has to be checked — it may trade
   the very legibility the change is for.

Point 2 is the one that could invalidate the whole direction, so it is the first
thing to measure, not the last.

## Part 3 — what I would do next, in order

1. **Land the identity fix** — `--unique-uid=0` as a playbook task with a
   read-back (`occ user:list` contains `akadmin`), plus the drift gate. Small,
   independent, and valuable even if the fs core never moves.
2. **Two spikes, timeboxed, before any commitment:**
   - **oCIS spike:** run the binary on the host, point it at a directory, open a
     `.docx` through our ONLYOFFICE via WOPI, save, and `ls` the storage. That
     single run answers both open questions above.
   - **Nextcloud-as-is spike (S-1):** the external-storage mount, RW, one user.
     A day, and it is the fallback if oCIS fails either check.
3. **Then choose**, with two working systems on the bench instead of a table.

The operator is right that this is the moment: no users, no migration, and every
week it waits the cost grows.

## Sources

- [Nextcloud admin manual — external storage & occ files](https://docs.nextcloud.com/server/latest/admin_manual/occ_files.html)
- [ONLYOFFICE — using WOPI (supported since 6.4)](https://github.com/onlyoffice/api.onlyoffice.com/blob/master/site/docs/docs-api/using-wopi/overview.md)
- [SFTPGo — Event Manager](https://docs.sftpgo.com/2.6/eventmanager/)
- [SFTPGo — OIDC](https://docs.sftpgo.com/2.6/oidc/)
- [SFTPGo + Collabora Online](https://sftpgo.com/collaborative-office-document-editing-sftpgo-collabora-online)
- [5 ownCloud alternatives, 2026](https://sliplane.io/blog/5-awesome-owncloud-alternatives)
- [Nextcloud vs ownCloud vs Seafile](https://massivegrid.com/blog/nextcloud-vs-owncloud-vs-seafile-enterprise-comparison/)
- [Best self-hosted cloud storage, 2026](https://talos.tools/blog/best-self-hosted-cloud-storage-2026)
