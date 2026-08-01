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

## Part 2b — Apple's `container`, and the custom-distro idea

Researched 2026-08-01 on operator suggestion. The estate runs **macOS 26.5.1**
(measured), which is exactly what `apple/container` requires — *"`container` is
supported on macOS 26, since it takes advantage of new features and enhancements
to virtualization and networking in this release"*. It is **not installed here**.

### What it is, and what it changes

VM-per-container: each container gets its own lightweight VM and its own kernel,
instead of Docker Desktop's one shared VM. Swift, open source, Apple-silicon
only. Better isolation, and on macOS 26 container-to-container networking works
(on macOS 15 the vmnet framework isolated them from each other entirely).

### The fact that decides whether it helps US — and it is NOT settled

**Apple's own docs do not say how host directories are shared.** The technical
overview says only *"you mount only necessary data into each VM"*. Secondary
sources state it is **virtiofs** — the same mechanism Docker Desktop uses.

If that is right, then **switching runtimes does not fix anything we care about**:
ownership still remaps, and the substrate that blocked `restic` and forced the
`keap.db` backup container-side is unchanged. The isolation and startup wins are
real; the filesystem story is the same story.

**This is the single measurement worth taking**, and it is cheap: install
`container`, mount a directory, `stat` a file inside and outside, write as the
container user and read the owner from macOS. One afternoon answers whether any
of the rest is worth designing.

### The custom-distro idea, taken seriously

> *a lightweight distro that handles communication between the OS and the Docker
> stacks*

VM-per-container makes this more coherent than it sounds: one VM whose job is to
**own the filesystem on a real Linux block device** — not a virtiofs share — and
serve it to everything else. Inside that VM, `chown`/`chmod`/groups are real,
because it is a real Linux filesystem with one uid namespace. That is the
user/group/permission model the operator asked for, actually enforced.

**But it collides with the other requirement, and the collision is the point:**

> *soubory bych samozřejmě rád procházel i klasicky přes `ls`*

These two pull apart:

| store | real POSIX semantics | `ls` from macOS |
| --- | --- | --- |
| APFS directory + virtiofs (today, and `container` too) | **no** — ownership remapped, uid per container | **yes** |
| Linux block device inside a VM | **yes** | **no** — macOS cannot read ext4/xfs |
| Linux VM + NFS/SMB export back to macOS | **yes**, inside | **yes**, over a network mount |

So the idea *can* have both — but only through the third row, which puts a
network filesystem in the path and makes the VM a hard dependency for `ls`. That
is a real cost, and it is the honest shape of the trade rather than a reason to
drop it.

### Where this lands

Ranked by what each actually buys:

1. **The host-daemon fs core (Part 2) does not need any of this.** A Go binary on
   macOS reads APFS natively — no virtiofs, no VM, and containers already reach
   the host in this estate. It gets the performance and the loopback visibility
   *without* the runtime change. **It remains the recommendation.**
2. **`apple/container` is worth measuring on its own merits** — VM-per-container
   isolation and startup are genuine — but as a **Docker Desktop replacement**,
   not as a filesystem fix. Those are separate decisions and should not be
   bundled.
3. **The custom distro is the most interesting and the least urgent.** It is the
   only option that makes `chmod` real, and the only one that needs a network
   filesystem to stay `ls`-able. Worth a design once the fs core question is
   settled — not before, because the fs core answer may make it unnecessary.

## Part 2c — container-per-user

Operator idea, 2026-08-01. It is the strongest of the three, because it does not
compete with the fs-core question — it **changes what that question is asking**.

### What it fixes that nothing else did

Part 1 of the companion spec recorded code-server as unfixable: one container,
one workspace, behind a forward-auth gate. Mounting every user's tree into it
would hand anyone who reaches it everyone's files, *"which is precisely the
partition the VFS exists to enforce"*. Per-user instances are the answer that was
sitting right there — each one mounts `users/{uid}` and nothing else.

And it generalises. Today the per-user boundary is enforced **in code**: Bone's
realpath-in-scope guard, face's uid pinning from forward-auth headers, KEAP's
tier ladder. Good code, and all of it is one bug away from a leak. With a
container per user, the boundary is enforced **by the mount** — a container
cannot leak bytes that were never mounted into it. The guard becomes
defence-in-depth instead of the only defence.

### Why it reframes the fs-core choice

Nextcloud, oCIS and Seafile are all being evaluated partly for something a
container boundary would provide for free: **multi-tenancy**. If each user's
editor and file browser run in their own container over their own subtree, the
store no longer has to know about users at all.

That admits much smaller tools — a plain WebDAV server, a file browser, even
`dufs` — where today the shortlist is dominated by applications whose main
complexity *is* the multi-tenant layer. **Worth deciding before the oCIS spike,
because it changes what the spike is testing for.**

### Where it fits the substrate

`apple/container` is a better match for this than Docker Desktop, and for once
the reason is architectural rather than benchmarks: VM-per-container means each
user's editor has **its own kernel**, and fast start is exactly the property an
on-demand per-user container needs. The two ideas were raised separately and
reinforce each other.

### The costs, and they are real

- **Multiplication.** N users × M per-user apps. Memory is the binding constraint
  on a Mac already running ~50 services. This is right for a *handful* of
  interactive surfaces — editor, file browser, terminal — and wrong for the
  infrastructure tier. **Naming which apps go per-user is the first design step,
  not an implementation detail.**
- **Lifecycle.** Something must start a user's container on first access and reap
  it when idle. That is new orchestration — and it is precisely the
  "pulse-driven organelle shots" shape already proposed, so it has a home.
- **Routing.** Traefik must send a request to *that user's* backend. Authentik
  forward-auth already puts the uid at the edge, so a uid-keyed router is
  feasible — but it is new machinery on the path everything else depends on.
- **Cold start** on first access after idle.

### The boundary, stated

Not everything should be per-user, and ONLYOFFICE is the clean counter-example:
it is **stateless** — it fetches a document, edits it, posts it back. A per-user
document server would multiply memory for no isolation gain, because it holds
nothing between sessions. The rule that falls out:

> **Per-user when the container holds per-user state or mounts per-user bytes.
> Shared when it is a stateless function over a document.**

That single line decides most cases without further argument, and it is worth
writing into the anatomy doctrine regardless of whether this gets built.

### What it would take to know

A one-user spike: one code-server container mounting only `users/akadmin`, routed
by uid, started on demand. It answers the memory question, the routing question
and the lifecycle question at once — and if it works, the fs-core shortlist gets
shorter rather than longer.

## Part 2d — the spike, RUN (2026-08-01, measured on this machine)

`brew install container` → 1.2.0, Apache-2.0, a launch **agent** (so
`container system stop` + `brew uninstall` is a clean exit). Docker Desktop was
untouched throughout: **63 containers up before, during and after.**

### Measurement 1 — the filesystem question, settled

This is the cheap measurement Part 2b said would decide whether the runtime
change helps. It does not.

```
$ container run --rm -v $D:/probe alpine sh -c 'stat -c "%u:%g mode=%a" /probe/host.txt; mount | grep probe'
0:0 mode=640
virtiofs on /probe type virtiofs (rw,relatime)
```

| | macOS sees | container sees |
| --- | --- | --- |
| host-written file | `pazny:staff` mode 640 | **`0:0`** mode 640 |
| container-written file | `pazny:staff` mode 644 | `0:0` mode 644 |

**`apple/container` shares host directories over virtiofs** — the same mechanism
as Docker Desktop, confirmed directly rather than from a secondary source. Mode
bits survive; **ownership is squashed to root in both directions**. And
`chown 1000:1000` inside the container **succeeded and did nothing** — no error,
no effect: a silent no-op, the same class this estate spent the day hunting.

**Conclusion: `apple/container` is a Docker Desktop alternative, not a filesystem
fix.** The chmod/ownership problem is a property of the host-sharing mechanism,
not of the runtime, and both runtimes use the same one. Part 2's host-daemon
recommendation stands unchanged.

### Measurement 2 — container-per-user, and the numbers are good

Two user trees, one container each, mounting only its own subtree:

```
sees own:      akadmin private notes
sees sarka:    can't open '/home/../sarka/documents/secret.txt': No such file or directory
traversal:     can't open '/../sarka/documents/secret.txt': No such file or directory
```

**The isolation is structural, as predicted.** Not a guard that can be bypassed —
the bytes are not in the VM.

| | measured |
| --- | --- |
| start, image local | **0.65 – 0.73 s** per user |
| host RSS per running VM | **~26 MB** (21 MB at `--memory 256m`) |
| network | each container gets **its own IP** (`192.168.64.5/.6/.7`) |

The `MEMORY` column reports the VM's *allocation* (default 1024 MB, and the
`container system config` tutorial is exactly how to lower that default). The
host RSS shows it is **lazily allocated, not reserved** — ~26 MB actual for an
idle container, and dropping the allocation to 256 MB barely moved it.

**All three unknowns from Part 2c came back favourable:**

- **memory** — 26 MB per idle user is affordable; ten users is a rounding error
  next to the 63 Docker containers already running;
- **start** — 0.7 s is inside the window where on-demand start is invisible
  behind a page load;
- **routing** — a per-container IP means Traefik has something concrete to route
  a uid-keyed request *to*, rather than needing a new addressing scheme.

### What this changes

Container-per-user is now the **best-evidenced** of the three ideas, and the only
one whose numbers were measured rather than argued. It also does not depend on
`apple/container`: the isolation and the economics would look similar under
Docker, and the VM-per-container kernel separation is a bonus rather than the
mechanism.

**It remains true that per-user is right for a handful of interactive surfaces
and wrong for the infrastructure tier** — that boundary rule (per-user when it
holds per-user state or mounts per-user bytes) is unaffected by these numbers.

### Not yet measured

- A **realistic image**. Alpine is 8 MB; code-server is ~1 GB and will start far
  slower than 0.7 s cold. The start-time number is a floor, not a promise.
- **Lifecycle** — nothing here started or reaped a container on demand.
- **Traefik uid-keyed routing** — feasible-looking, untried.

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
- [apple/container — README (macOS 26 requirement)](https://github.com/apple/container)
- [apple/container — technical overview](https://github.com/apple/container/blob/main/docs/technical-overview.md)
- [Apple Containers on macOS: a technical comparison with Docker](https://thenewstack.io/apple-containers-on-macos-a-technical-comparison-with-docker/)
- [Apple Container vs. Docker Desktop](https://4sysops.com/archives/apple-container-vs-docker-desktop/)
