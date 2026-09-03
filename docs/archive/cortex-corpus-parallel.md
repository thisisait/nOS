# S2 — Corpus in parallel: the design

Stage **S2** of `docs/archive/cortex-self-core.md` §6. Written 2026-07-26 on
`feat/cortex-corpus-parallel`. Design only — nothing was built, deployed or
mutated; the live KEAP store was not touched, the user tree was read and never
written.

Read §0 first. It is the reason this stage is smaller than its name suggests,
and the reason its own success gate cannot be trusted without a denominator
printed beside it.

---

## 0. What this stage actually moves, measured today

Re-measured 2026-07-26 by direct read of the host tree (`find`, no writes):

| thing | count | what it is |
| --- | --- | --- |
| `tenants/pazny/users` — total files | **5** | the tree fs-sync walks |
| …of which Bone per-user SQLite | 3 | `akadmin/.face/state.db`, `-shm`, `-wal` |
| …of which noise | 1 | `users/.DS_Store` |
| …of which **real documents** | **1** | `akadmin/documents/pazny prvni pokus/FORMULAR_…dohoda_o_srazce.pdf` |
| `users/nos-docs` | **empty** | pre-created bind-mountpoint; content is elsewhere |
| `shared/nos-docs` — total files | 176 | the second mount, host-side |
| …of which under `nOS/` (mirrored) | **166** | the self-model card tree |
| …of which under `canonical/` (not mirrored) | 10 | read by `ingest.mjs`, not fs-sync |

166 + 1 = **167**, which is exactly S0's `fs:*` row count. The composition is
confirmed end to end, and the arithmetic closes with nothing left over.

**So: porting fs-sync moves one PDF.** The other 166 objects are the estate's own
self-model, which `runSelfmodel()` in `server/cortex-store.ts` already generates
— the organ produces that content itself and has done since C1. Nothing in this
stage is a migration. No corpus is being rescued.

State it plainly in every report this stage produces:

> S2 stood the ingestion path up. It did not move a corpus, because there is not
> one yet. One user document exists.

That is not a failure — it is the whole argument for doing it now. An ingestion
path built against 1 file and 166 generated cards can be got wrong cheaply. The
same path built after a company's material has landed gets one shot, and its
first bug is a prune. **The value here is sequence, not volume.**

### The consequence for the diff harness (§6)

The S2 exit in `cortex-self-core.md` §6 — "organ and KEAP corpora agree on row
counts and ids **exactly** … for three consecutive nights" — is satisfiable
tonight and proves almost nothing. Two near-empty sets agreeing that they are
near-empty is not evidence that ingestion works.

The harness is therefore designed to **report its own denominator above its
verdict**, and to refuse the word "green" while that denominator is small. The
work that actually validates the port is a separate, organ-only fixture suite
(§6.3) which never touches the real tree and never claims to be a night.

---

## 1. fs-sync as a host reader

### 1.1 Decision

Port `server/fs-sync.ts` into the organ **as the users pass only, driven by an
explicit list of roots**, and read the host tree directly. The bind mount
disappears; nothing replaces it.

**Scope, honestly:** the change is ~1 550 lines of port for 1 document of new
content. That is acceptable *only* because it is also the path every future
document arrives on, and because most of the cost is already paid — see 1.2.

### 1.2 The port set, and the good news

`files/anatomy/cortex/server/db.ts` is **byte-identical** to KEAP's
(`diff` = 0 lines, verified today, against a KEAP tree at v1.35.0). Every DB
function fs-sync needs is therefore already in the organ:

`saveObject` · `getObjects` · `deleteObject` · `getObjectSyncIndex` ·
`countObjectsByOwner` · `listFsMappings` · `upsertEmbeddings` · `pruneEmbeddings`

What is missing is the thin layer above it:

| module | lines | why needed | verdict |
| --- | --- | --- | --- |
| `uid.ts` | 54 | `canonicalUid` — the uid derivation itself | port verbatim |
| `objects.ts` | 76 | `extractRefs`, `anchorNodeIds`, `objectText` | port verbatim |
| `search.ts` | 146 | `markCorpusDirty` | port verbatim |
| `fs-roots.ts` | 147 | `listRoots`, `resolveInRoot` — mapped-folders registry | port verbatim, inert |
| `fs-sync.ts` | 813 | the pass | port, one marked change (1.4) |
| `embeddings.ts` | 138 | `pendingEmbeddings` — the embed diff | port verbatim |
| `intake.ts` | 179 | `/ingest/v1/capture` — the consolidator's target | port verbatim |
| `server/index.ts` | +4 routes | `/agent/v1/embeddings{,/pending}`, `/ingest/v1/{capture,health}` | new, lifted from KEAP `agent.ts:338,345` |

**`fs-roots.ts` is ported even though the organ has no admin UI for mappings.**
Cutting it would force edits inside `fs-sync.ts` (which imports it at module
level and calls `syncMapping` from `syncAllFs`), and edits are what turn "re-sync
from KEAP is a `cp`" into "re-sync is a patch a careless merge drops". With
`KEAP_FS_ROOTS` unset, `listRoots()` returns `[]` and `db.listFsMappings()`
returns `[]` — the whole second half is inert. Keeping it costs 147 dead lines
and buys byte-identity, which is the organ's own stated doctrine
(`cortex-config.ts` header). Take the dead lines.

### 1.3 Permissions: the container→host change is a non-event, and S0 already proved why

fs-sync reads **no** `st.uid`, no `getuid()`, no ownership, no mode. Attribution
is `canonicalUid(<top-level directory NAME>)` (`fs-sync.ts:434-445`) hashed into
`fs:<uid>:<sha1(relPath)[:16]>` (`:473`). Visibility is
`SHARED_UIDS.has(uid) ? 'shared' : 'private'` (`:479`) from a config set.

A host daemon running as `pazny` therefore derives **the same ids and the same
visibility** as container-`node` against a RO mount. Real filesystem permissions
replace the RO mount as the *enforcement* of read-only-ness — the organ simply
never opens a file for writing — but they feed nothing the derivation consumes.

One thing genuinely improves. S0 flagged that on a VirtioFS bind mount a
directory can enumerate while file bodies read empty, and `bodyOf` swallows the
error and upserts a correct-size node with an **empty body** — a
content-fidelity failure the prune guards do not catch. VirtioFS is the Docker
Desktop bind layer. **The host daemon reads native APFS and is not exposed to
it.** Moving to the host removes that hazard rather than inheriting it.

Add the cheap guard anyway, because it costs nothing and the class of failure
(silent empty body) is exactly the class this system must not have:

> For a `TEXT_EXT` file with `size > 0`, an empty parsed body is counted into a
> new `emptyBodies` field on `FsSyncResult`, and must not overwrite a previous
> non-empty body. Surfaced as data, like `pruneRefused` and `danglingAnchors`.

### 1.4 Reproducing the composition — and the trap not to fall into

`/user-files` is two host trees stacked at one path. The organ has no compose
file, so the composition must become explicit. Three candidate mechanisms:

- **A symlink farm** (`~/cortex/run/user-files/nos-docs -> …/shared/nos-docs`).
  **Does not work, and fails silently.** `syncUserFiles` does
  `lstatSync(userDir)` then `if (!st?.isDirectory()) continue` — an `lstat` on a
  symlink reports `isSymbolicLink()`, `isDirectory() === false`, so the uid is
  **skipped**, and `walkDir` skips symlinks too by explicit doctrine
  (`:303`, realpath ∈ scope). No error, no log, the whole self-model just is not
  there. Recorded here so nobody spends an afternoon on it.
- **A host bind mount.** macOS has no `mount --bind` without macFUSE/bindfs; the
  Linux form needs root. A new dependency and a privilege escalation for a user
  daemon. Rejected.
- **A roots list in the code.** Chosen.

**Decision:** generalise `USER_FILES_DIR` (a single string) into an ordered list
of roots, each declaring how uids are derived:

```
{ path: "<nos_data_root>/tenants/<slug>/users", uid: "child-dirs" }
{ path: "<shared root>",                        uid: "literal:nos-docs" }
```

`child-dirs` is today's behaviour verbatim (iterate top-level dirs, canonicalise
each name). `literal:<uid>` walks the root as if it *were* one uid's directory.
Both then hit the same `walkUser` → same `relPath` → **same ids**: for the shared
root, `SYNC_DIRS` still gates on `nOS`, so `relPath` is `nOS/<stack>/<file>.md`,
identical to what the container derives through the nested mount.

Offer this upstream to KEAP as a PR. KEAP's compose stack already expresses
exactly this composition; the code just cannot see it, which is why S0 had to
find the coupling in a mount file. Making it visible in the code is strictly
better for both consumers and keeps **one** implementation. If upstream declines,
carry it as the organ's second seam file alongside `cortex-ann.ts` /
`cortex-config.ts`, with a test pinning that `fs:` id derivation is unchanged for
both root shapes.

### 1.5 Which tree the shared uid reads — and the divergence nobody has noticed

Two candidate sources for the `nos-docs` uid:

1. **`keap_selfmodel_root`** (`…/tenants/<slug>/shared/nos-docs`) — the tree the
   converge publishes and RO-mounts into KEAP. It is a **host, nOS-owned** tree,
   not a KEAP artefact.
2. **`<cortex_store_path>/selfmodel-stage/cards`** — the organ's own generated
   card tree. `runSelfmodel()` already writes it and then **ignores it**: it uses
   only `<stage>/canonical`, so `<stage>/cards/nOS/**` is generated on every
   materialise and never read.

Option 2 matches the organ's doctrine ("one source, no shared directory, no
dependency on KEAP being deployed", `cortex-config.ts:126`). **It is still the
wrong choice for S2**, because of a divergence found today:

> `roles/pazny.keap/tasks/selfmodel.yml:99-127` invokes the generator with
> `--uid`, `--top`, `--deps-json`, `--anchors-json` and **`--facts-json`** (live
> per-service image/version/port/domain/mem_limit/cpus).
> `cortex-store.ts::runSelfmodel` (`:388-395`) passes **none of them**.

`--uid`/`--top` default correctly (`nos-docs`, `nOS`), so ids would still match.
`--facts-json` does not: the organ's card **bodies** would lack live deployment
facts. Same ids, different content hashes, different vectors — and S3's premise
("one corpus, two indexes") quietly false while the id diff reads green.

**Decision:** during S2 the shared uid reads **option 1**, the published host
tree, behind a new var `cortex_fs_shared_root`. A comparison against a different
input is not a comparison.

This is a **transitional coupling with a named exit**, not a doctrine reversal:

- It must **fail loudly** when the configured root is absent — absence is not
  emptiness (§1.6).
- The exit is one sized change: the converge writes `{{ _keap_sm_facts }}` to a
  host JSON file (`cortex_selfmodel_facts_path`), `runSelfmodel` passes it
  through as `--facts-json`, and the source flips to option 2 with the id+hash
  delta recorded in the flip's commit. Scheduled in **S4**, when KEAP's copy
  stops being the reference anyway.
- `--enabled-json` is passed by *neither* caller today, so the enabled set is not
  a divergence right now. It becomes one the moment either side starts passing
  it. Written down so that day is not a mystery.

### 1.6 Prune guards — kept, and they matter more here

Port all four verbatim. They are already correct (S0 §B) and only need carrying:

| guard | fires when | `fs-sync.ts` |
| --- | --- | --- |
| root absent | `!existsSync(USER_FILES_DIR)` → no-op return | `:424` |
| cap hit | `found >= MAX_FILES` (20 000) → refuse prune | `:527` |
| walk truncated | any `readdir` failed (EACCES, dropped sub-mount) → refuse | `:534` |
| zero-scan | 0 files found while mirrors exist → refuse | `:545` |
| **per-uid zero-scan** | a uid contributed 0 files but has mirrors → hold back | `:550-580` |

With a 167-object corpus of which 166 belong to one uid, the per-uid guard is
the only thing between a transient mount failure and losing the entire
self-model mirror plus its vectors. The plan's framing is right: these matter
**more** at this size, not less. A single-uid corpus is the exact shape the
global zero-scan guard was too coarse for, which is why the per-uid one exists.

`pruneRefused` stays surfaced as data (`FsSyncResult`), and the nightly diff
reads it — a refusal must look like a refusal, never like "nothing to remove".

### 1.7 The host-side mount assertion (§8.3 of the plan)

`nos_data_root` = `/Volumes/SSD1TB/nOS/data`, a removable volume. The existing
`tasks/stacks/docker-external-mount-preflight.yml` probes the **Docker VM's**
ability to bind it; a host daemon goes nowhere near that path. Confirmed today:
no host-side sentinel or assertion exists.

**Decision: a converge-written sentinel, checked before any walk.**

- Ansible writes `{{ nos_data_root }}/.nos-mount-ok` (JSON: tenant slug, volume
  UUID, converge timestamp). It lives at `nos_data_root`, **not** inside
  `tenants/<slug>/users` — the user tree stays untouched, per the hard
  constraint.
- The organ reads it before every pass and asserts slug + presence.
- Missing or mismatched → **refuse the whole pass**, exit non-zero, notify. Do
  not walk, do not prune, do not fall through to the zero-scan guard.

The zero-scan guard remains as the second line, but S0's objection stands and is
honoured: correctness must not rest on a guard *reacting* to an unmounted disk
when it can rest on never walking one. A directory can also survive an eject as
a stale empty mountpoint — a sentinel distinguishes that from a genuinely empty
tree; a `find` cannot.

### 1.8 FLAG, DO NOT FIX — Bone's per-user SQLite lives inside the knowledge tree

`{{ nos_data_root }}/tenants/<slug>/users/<uid>/.face/state.db` (+ `-wal`,
`-shm`) is Bone's per-user state (`files/anatomy/bone/userstate.py`, `chmod
0700`). It sits **inside the tree the knowledge system walks.** Three of the five
files in that tree are it.

It is excluded today by **two independent guards**, and both are accidents of
configuration rather than a stated policy:

1. `walkDir` skips any entry whose name starts with `.` (`:299`) — `.face` is
   hidden.
2. `.face` is not in `KEAP_FS_SYNC_DIRS` (`documents,library,inbox,nOS`).

Widen that allowlist — or add a "mirror everything" mode, which is a natural
future request for BYOD — and Bone's user state enumerates into the knowledge
corpus. `TYPE_BY_EXT` even maps `db`/`sqlite` → `'database'`, so the code would
ingest it as a recognised type without complaint. `bodyOf` would not read the
bytes (not in `TEXT_EXT`), so the leak is metadata: which users have a store, its
size, its mtime, its path — surfaced in `/api/graph`, in search, and in the
directory-stat layer that ships repo-flagged folders to the client.

**Not fixed here.** The two obvious fixes — a deny-list of state-bearing paths,
or moving Bone's store out of the knowledge tree entirely — are both real changes
to a live organ's on-disk layout and belong to whoever owns that decision. Filed
so that the day someone widens the allowlist for a good reason, this is already
written down.

---

## 2. A second write target, not a moved one

### 2.1 Shape

`keap-consolidate.py` and `keap-embed-sync.py` become **fan-out** jobs: sweep
once, feed N targets. Targets are declared as a list, incumbent first:

```
targets:
  - name: keap    base: http://127.0.0.1:8091  token_env: KEAP_AGENT_TOKEN_*
  - name: cortex  base: http://127.0.0.1:8098  token_env: CORTEX_AGENT_TOKEN_*
```

**Distinct env names per target is not cosmetic.** The organ is a verbatim port
and reads `KEAP_AGENT_TOKEN_RO/RW/CAPTURE` (`server/tokens.ts`) — inside the
organ's process those names hold the *cortex* secrets, set by its plist. A
fan-out job holding both targets' credentials under one name would, on the first
copy-paste, POST KEAP's write token to the organ or vice versa. One name, two
secrets, on one host, is how a token ends up somewhere it was never scoped for.

### 2.2 Idempotence against both targets

Already true, and it is what makes the rest simple:

- **Captures** — `sid(key) = "dp-" + sha1(source key)[:24]` is deterministic, and
  `/ingest/v1/capture` upserts on it. A re-POST updates the same queue row.
- **fs objects** — `fs:<uid>:<sha1(relPath)[:16]>`, and `saveObject` upserts.
- **Embeddings** — `PRIMARY KEY (kind, ref_id)`, `upsertEmbeddings` upserts;
  `content_hash` makes a re-embed of unchanged text a no-op at the diff stage.

So every write is **at-least-once with a deterministic key**, which at the store
is exactly-once. That means the fan-out is free to be *pessimistic*: when unsure
whether a target received an item, send it again. Nothing duplicates.

### 2.3 The one real hazard: the shared state file

`~/.nos/keap-consolidate-state.json` records `{fs: {path: "mtime:size"}}` and
`{mariadb: {...}}` and is written by the `finally` block — one state, one
target's worth of truth. Add a second target naively and this becomes a **silent
data-loss bug**: item accepted by KEAP → signature recorded → the organ, which
rejected it or was down, **never sees it again**, because the next sweep skips
it as unchanged. The corpora then differ forever and the diff blames ingestion.

**Decision: the state file grows a target dimension.**

```json
{ "version": 2,
  "targets": {
    "keap":   { "fs": {...}, "mariadb": {...} },
    "cortex": { "fs": {...}, "mariadb": {...} } } }
```

Migration is mechanical: a v1 file (top-level `fs`/`mariadb`) is read as
`targets.keap.*`, so the incumbent does not re-sweep 128 captures on the first
run under the new job. Write it as a read-time shim, not a migration script.

### 2.4 Partial failure — one target accepts, the other rejects

**Per-target isolation, no rollback, source-side budget.**

1. **Never un-write the target that succeeded.** There is no distributed
   transaction here, and simulating one means issuing a *destructive* write in
   response to a *transport* error. Deleting a row from KEAP because the organ
   was restarting is the worst possible trade.
2. **Record state per target, after that target's ack.** The failed target's
   signature is not written, so the next run retries it and only it.
3. **The budget (`NOS_CONSOLIDATE_MAX`, default 200) is decremented per swept
   item, not per POST.** Otherwise the second target halves the effective sweep
   rate, and a lagging target starves permanently behind a moving cap.
4. **Effects outside the stores happen once**: the MariaDB `docker exec` sweep
   runs once and its rows feed both; the ntfy/Wing notification fires once with a
   per-target breakdown; Ollama is called per target (§4.2) but sequentially.
5. **The incumbent's health decides the exit code.** Today the job exits 2 if
   KEAP is unreachable. Under fan-out: a target that fails preflight is
   **skipped with a recorded reason**; the run exits non-zero **only if the
   incumbent failed**. The organ's failure is reported at `low`/`medium` and
   shows in the diff as a skipped night (§5).

Point 5 is the load-bearing safety property of the whole stage:

> **The parallel target must never be able to degrade the incumbent.**

The organ is new, unproven, and single-process on a laptop. If a crashed organ
could abort the sweep, then standing up the shadow would make the production
knowledge pipeline *less* reliable than it was before — paying a real cost for a
measurement. Wire the failure domains apart on day one; it is much harder to
retrofit after the first 03:00 page.

### 2.5 What the fan-out does **not** do

It does not read from one target and write to the other. Neither corpus is ever
sourced from the other. Both are built from the same host sources,
independently — that independence is the experiment, and any shortcut that
couples them destroys the thing being measured.

---

## 3. Is this two writers on one store?

**No. Two stores, each with exactly one writer, fed from one source.** And the
distinction is not a technicality — it is the specific hazard the design docs
name, and it is absent here.

### 3.1 What the warning is actually about

`nos-cortex-organ-design.md` §7 Q1 and `cortex-config.ts:27-31` forbid a *shared
`keap.db`* — two processes holding write handles on **one libSQL file**. The
concrete failures:

- two `runMigrations()` racing schema changes on one file;
- `cortex-ann.ts` doing `DROP INDEX` + `CREATE INDEX` on the DiskANN shadow table
  while another process reads or writes vectors through it;
- WAL / `-shm` lock contention between processes with different journal
  expectations;
- two competing `db_identity` claims, which would destroy the one field that
  answers "is this the same database?" — the field that caught the 2026-07-22
  wipe;
- and the one that kills S3 outright: **a reader cannot build its own tuned ANN
  index in a file it does not own**, so a shared store would force the organ onto
  KEAP's untuned 514 MiB index and there would be no comparison to make.

### 3.2 Why none of it applies

| | KEAP | organ |
| --- | --- | --- |
| file | `/data/keap.db` inside `iiab-keap-1` | `~/cortex/data/keap.db` on the host |
| filesystem | container volume | APFS (host) |
| writing process | the KEAP node server | the cortex node daemon |
| `db_identity` | KEAP's | `78889db5-9907-44e4-87ed-fc3649130ee3` |
| ANN index | default (`libsql_vector_idx(vector)`) | `float8` + `max_neighbors=20` |

Same basename, different directory, different file, different identity. The
feeders are **HTTP clients**: they hold no DB handle at all, and each target's
own server process is the only writer to its own file. There is no shared lock,
no shared WAL, no shared shadow table, no shared migration.

And the misconfiguration that *would* create the two-writer case fails closed:
`cortex-store.ts::assertClaimable`/`assertOwnStore` refuse to open a store file
the organ did not create, and `cortex-config.ts` deliberately does **not** honour
`KEAP_DATA_DIR` precisely so an unconfigured organ gets its own default instead of
aiming itself at another service's live file.

### 3.3 What the real hazard is, since it is not corruption

It is a **coordination** hazard, and it lives entirely in the feeders:

1. **The shared state file** (§2.3) — the only genuinely shared mutable state in
   the design, and therefore the only place a real bug can live. Fixed
   structurally by the target dimension.
2. **Double side-effects outside the stores** — notifications, `docker exec`
   load, Wing audit rows. Fixed by sweeping once and fanning out (§2.4.4).
3. **Ollama contention** — one embedder, two passes. Sequenced (§4.2); the
   nightly schedule already has 30-minute gaps.
4. **Token confusion** — one env name, two secrets (§2.1).
5. **Divergence** — the two stores drift apart. This is not a bug to prevent. It
   is the measurement (§6).

---

## 4. Embeddings

### 4.1 Cost

The organ embeds against the same host Ollama, doubling the nightly pass.
Measured full pass: **17.7 s**. Doubling is not a consideration.

A shared vector cache keyed on `(model, content_hash)` would halve it and would
*not* hide divergence (a divergent text yields a different hash, hence a miss).
**Rejected anyway, for S2:** independence is the product of this stage. Two
pipelines that share a cache are one pipeline with two outputs. Revisit
post-S3, when there is something to optimise for.

### 4.2 Sequencing

Two separate passes, **incumbent first**, sequential, one after the other within
the `keap-embed-sync` slot (04:45 UTC). Each pass is self-contained: its own
`/agent/v1/embeddings/pending` diff, its own Ollama calls, its own POST-back.
The pending sets differ per store by construction, so there is nothing to share.

### 4.3 Comparability — enforced, not assumed

Do **not** tune anything in S2. `ANN_DEFAULTS = {compressNeighbors: 'float8',
maxNeighbors: 20}` is already the organ's shipped tuning and `db.ts` ships the
plain default index that KEAP runs on. **That asymmetry is the S3 experiment.**
Leave `CORTEX_ANN_COMPRESS_NEIGHBORS` / `CORTEX_ANN_MAX_NEIGHBORS` unset, and
leave KEAP alone. Written here so a later well-meaning change does not "fix" the
asymmetry and delete the experiment.

Comparability then reduces to three things, two of which are already free:

- **Model.** `EMBED_MODEL = process.env.KEAP_EMBED_MODEL ?? 'nomic-embed-text'`.
  The wire protocol already carries it: `/embeddings/pending` returns
  `{model, dim}` and the job embeds with what the server declared. **Gate:**
  before either pass, assert the two servers declare the same `(model, dim)`;
  on a mismatch, **refuse the run** and record a red night. One assertion turns
  a silent incomparability into a visible halt.
- **Dimension.** Fixed at 768 by `embeddings.vector F32_BLOB(768)` on both sides;
  changing it requires `DROP TABLE embeddings`. Nothing to do.
- **Corpus.** Not equal today. This is the S2 blocker below.

### 4.4 The corpus-parity blocker (measured today)

| tree | nodes |
| --- | --- |
| organ `files/anatomy/cortex/knowledge/canonical` (108 files) | **1 750** |
| KEAP working tree at v1.35.0 | **2 403** |
| KEAP live container, taxonomy embeddings (S0) | **1 841** |
| nOS pin `keap_repo_ref` | v1.32.1 ("taxonomy grew 1750 → 2393", commit `7bdad0cc`) |

Three numbers, and none of them is "the corpus". The organ carries the v1.27.0
canonical tree; the pin moved twice since; the live container has not ingested
the pinned tree. "One corpus, two indexes, one recall gate" is false as things
stand, and a recall comparison run over it would measure the taxonomy delta and
attribute it to the index.

**Decision: S2 pins corpus parity explicitly, as its own reviewable commit.**

1. Re-sync `files/anatomy/cortex/knowledge/` from the tag `keap_repo_ref` pins,
   recording node counts before and after in the commit message. This is a
   corpus prerequisite, **not** tuning — it touches no ANN parameter.
2. Re-run the onto1 conformance gate (`npm run conformance`) and the spine drift
   check. The 790-node reference digest `onto1:76d1f3ad728b382b` and the
   operational digest `onto1:5d9bef3706a3c8ac` are both expected to move; the
   *new* values get recorded, and any failure of the fixture cases (§2.2 fixpoint,
   §2.3 collision, §3.1 code-unit sort, §3.3 description-excluded) is a stop.
3. The nightly diff compares **taxonomy node id sets**, not just `fs:` object
   ids, and prints the parity state on every run.
4. If parity cannot be reached in S2, it is not silently deferred: S3's recall
   gate is restricted to the intersection and **must state its denominator**.

---

## 5. How long parallel runs, and what happens on the night they disagree

### 5.1 Policy: log and continue; the clock resets; three resets escalate

Decided now, not during.

| event | action |
| --- | --- |
| nights agree | clock +1; at 3, S2 exits |
| **nights disagree** | **log the full diff, continue**; clock → 0 |
| 3 disagreeing nights total (not necessarily consecutive) | stop adding nights; notify `high`; S2 reports and S3 decides on the evidence |
| a target was down / skipped | night is void, neither +1 nor a reset; recorded as skipped |
| **removal-shaped disagreement** (below) | **HALT immediately** |
| mount sentinel fails | pass refused before any walk; night void; notify |
| 14 nights elapsed | hard ceiling — S2 reports whatever it has, with the denominator |

### 5.2 Why continue rather than halt

Halting on the first disagreement turns a *measurement* harness into a deploy
gate, and it destroys the evidence it exists to collect. From one night you
cannot tell apart:

- a **bug** — the same disagreement, identically, every night;
- a **race** — a disagreement whose shape changes nightly;
- a **transient** — one night, never again.

Those three want completely different responses, and halting guarantees the
single sample that cannot distinguish them. Continuing costs nothing real,
because **nothing consumes the organ's corpus yet** — repointing readers is S4.
The organ is a shadow, and a wrong shadow harms nobody.

The counter-risk is the real one: a parallel run that never ends becomes
permanent furniture, and "we'll look at the diff eventually" becomes the
steady state. That is what the 3-reset escalation and the 14-night ceiling are
for. Both are named now so neither is negotiable later.

### 5.3 The one thing that halts immediately

**Removals are the only irreversible direction.** Everything else is additive
drift a re-sync repairs. So the harness halts the organ's fs-sync (set interval
0, notify `high`) when either holds:

- `organ.removed > 0` **and** the diff shows objects present in KEAP but missing
  from the organ — i.e. the organ pruned something the other side kept;
- the organ reports `pruneRefused` on a night where KEAP's corpus shrank — the
  guards did their job, but the underlying condition (a dropped mount, an
  unreadable subtree) is live and must be looked at before the next pass.

Halting fs-sync does **not** stop the diff from running; the next night still
records the state. Refusing to walk is safe. Refusing to observe is not.

---

## 6. The diff harness

### 6.1 Access rules

Both corpora are read over `/agent/v1/*` **only** — never host `sqlite3` against
the live KEAP db, never a container write, never a write of any kind. Per §3 of
`cortex-self-core.md`'s doctrine line: if the API is the only observable path, an
in-process shortcut is an unobservable call. That applies to the harness first.

### 6.2 What is compared

| set | compared on |
| --- | --- |
| `knowledge_objects` where `frontmatter.source='fs'` | id set (exact), and per id: `size`, `mtime`, `sha256(body)`, `visibility`, `type`, `title` |
| taxonomy nodes | id set (exact) — §4.4 parity |
| embeddings | `(kind, ref_id, content_hash)` — **not** vectors; vectors are the S3 experiment, not an agreement criterion |
| captures | id set |
| pass health | `pruneRefused`, `danglingAnchors`, `emptyBodies`, `skipped` sentinel, per-uid counts |

Body **hashes**, not bodies — that is what catches the VirtioFS-shaped empty-body
class and the `--facts-json` divergence (§1.5), both of which an id-only diff
reads as green.

### 6.3 What it cannot earn, and how it says so

The harness prints its **denominator above its verdict**, and the honesty is a
computed property rather than a comment someone deletes. Below a threshold of
**25 real user documents**, the report is required to end with the disclaimer:

```
S2 diff — night 3/3                                  2026-07-2x
  fs objects        167 = 167   ids exact   (166 nos-docs + 1 akadmin)
  real user docs      1         <- the denominator that matters
  taxonomy nodes   1841 vs 2393 MISMATCH — corpus parity not pinned (§4.4)
  embeddings      3355 vs  nnn  (model nomic-embed-text, dim 768, both)
  pruneRefused      no /  no    emptyBodies 0 / 0

  NOT EXERCISED tonight: multi-user attribution, prune, cap (20 000),
  EACCES truncation, visibility flip, move/rename, >1 tenant,
  bodies over BODY_CAP, non-ASCII paths.

  This run does not show that ingestion is correct. It shows that two
  near-empty corpora are equally near-empty.
```

### 6.4 The gate that does the actual validating — organ-only fixtures

The nightly diff measures **agreement**. A separate suite measures
**correctness**, and it is where the port is really tested.

Constraints, absolute: the fixture tree lives at `~/cortex/fixtures/user-files`
— **outside `nos_data_root`**, never mounted into KEAP, never inside the real
user tree — and is used only by a **local organ on a spare port against a copy of
its store**. It is a test, not a night, and it never appears in the 3-night
count.

It must exercise, at minimum: two uids; a shared uid; a prune (delete a file);
the per-uid zero-scan guard (empty one uid's tree while another has files — the
exact shape §1.6 protects); the cap; an EACCES subtree (`chmod 000`); a
visibility flip via `SHARED_UIDS`; a move/rename (delete+create, ids change,
embedding re-syncs); frontmatter `type`/`title`; a CRLF frontmatter block; a
document opening with a horizontal rule (the strict-parse case); a dangling
`[[node]]` anchor; a body over `BODY_CAP`; and a read that throws mid-body.

**These are the paths a corpus of one PDF cannot reach, and they are exactly the
paths that destroy data when they are wrong.**

---

## 7. Build order

1. Pin **corpus parity** (§4.4) — its own commit, counts recorded, conformance
   re-run. Blocks everything downstream that claims comparability.
2. Port the modules (§1.2): `uid` → `objects` → `search` → `fs-roots` →
   `embeddings` → `intake` → `fs-sync` (+ the roots-list change, §1.4).
3. Mount sentinel (§1.7): Ansible writes it, the organ asserts it. Before any
   walk exists that could run without it.
4. Organ routes: `/agent/v1/embeddings{,/pending}`, `/ingest/v1/{capture,health}`.
5. **Fixture suite (§6.4) green on a local spare-port organ against a store
   copy** — before anything is scheduled.
6. Fan-out the two Pulse jobs (§2), incumbent-first, per-target state, distinct
   token env names.
7. Diff harness (§6) as its own Pulse job, after `keap-embed-sync`.
8. Nights.

Steps 1–7 are code and reviewable. Step 8 is calendar.

## 8. Exit criterion, amended

`cortex-self-core.md` §6 S2 currently reads: *"organ and KEAP corpora agree on
row counts and ids exactly … for three consecutive nights."* Amend to:

> **Exit:** (a) corpus parity is pinned and the taxonomy id sets match, or the
> gap is recorded with its cause; (b) the fixture suite (§6.4) is green,
> including every prune-guard case; (c) the organ and KEAP corpora agree exactly
> on `fs:` object ids **and body hashes** for three consecutive nights, with the
> mount sentinel asserted on each; and (d) the report states the real-document
> denominator and lists what was not exercised.
>
> (c) alone is **not** sufficient and must not be reported as if it were.

## 9. Risks

| risk | mitigation |
| --- | --- |
| The 3-night green is read as "ingestion validated" | §6.3 disclaimer is computed and unremovable below 25 documents; §8 makes (c) explicitly insufficient |
| Symlink farm tried for the composition; uid silently vanishes | §1.4 records the exact `lstat` line that swallows it |
| `--facts-json` divergence makes S3's "same corpus" false while ids read green | §1.5 sources the shared uid from the published tree; §6.2 compares body hashes |
| A crashed organ aborts the sweep and starves KEAP | §2.4.5 — incumbent decides the exit code; failure domains split on day one |
| One state file suppresses the retry the second target needs | §2.3 target dimension + v1 read-shim |
| One token env name, two secrets, one host | §2.1 distinct names per target |
| Transient unmount → prune → 166 objects and their vectors gone | §1.7 sentinel refuses the pass; §1.6 five guards behind it; §5.3 removal-shaped halt |
| Parallel run becomes permanent furniture | §5.1 three-reset escalation + 14-night ceiling, both named now |
| Corpus parity deferred "just for now" | §7 step 1 blocks the rest; §4.4.4 forces a stated denominator if it slips |
| Backup: the store's "everything is derived" answer weakens | Still derivable — but derivation now depends on a **mounted removable volume**, not git. Re-read `nos-cortex-organ-design.md` §7 Q6 at S4, not here. The claim "S2 adds no row that a converge plus a mounted SSD cannot rebuild" was **false as first written** and is now true only because it was made true: the fan-out's signature ledger lives in `~/.nos`, OUTSIDE both stores, so a wiped store kept its ledger, every file signature still matched, and not one `dp-<sha1>` capture row was ever re-POSTed. `/ingest/v1/capture`'s health surface now publishes an opaque **store epoch** (a digest of `db_identity`), and `keap-consolidate` drops a target's ledger when that epoch changes — so `rm -rf ~/cortex/data` + converge rebuilds the captures too. **Ceiling:** KEAP's container publishes no epoch, so the incumbent's ledger is still manual; the nightly diff reports the gap as `feeder-ledger-ahead-of-store` with the state file named in the action |
| Bone's `state.db` mirrored into the corpus by a future allowlist widening | §1.8 — flagged, deliberately not fixed |

---

## 10. Build record — what shipped, and the counts it was measured at

Appended after the build (2026-07-26/27) on `feat/cortex-corpus-parallel`.
Nothing was deployed: no converge ran, the live KEAP store was read over
`/agent/v1` and never written, and the user tree was read and never written.
Every organ-side measurement below is from a LOCAL daemon on spare port **8198**
against a **copy** of the organ's store in `/tmp`.

### 10.1 Step 1 — corpus parity (§4.4), commit `e4003ea4`

The pin had moved again since the design was written: `keap_repo_ref` is
**v1.34.0**, not v1.32.1.

| tree | before | after |
| --- | --- | --- |
| `knowledge/canonical` nodes (108 files) | 1 750 | **2 393** |
| `knowledge/ontology/relations` typed edges | 0 (12 partitions absent) | **417** (12 partitions) |
| `facts.toeRelations` (materialised store) | 4 434 | **4 643** |
| onto1 conformance | 6/6 | 6/6 (unmoved — fixtures are a PORT statement) |
| `spine-render --check` | in sync | in sync (790-node spine untouched) |

The two literals that moved are corpus statements and were moved in the parity
commit itself, so no red suite is ever made green by editing a number quietly.

### 10.2 Steps 2–5 — the port, commit `b93cba92`

Ported verbatim: `uid.ts` `objects.ts` `search.ts` `fs-roots.ts`
`embeddings.ts` `intake.ts` (one marked, back-compatible change: the ingest
routes take an optional body parser so it runs AFTER the bearer check, never
before). `fs-sync.ts` carries **7 marked diffs**, all upstreamable. New seam
file `server/cortex-fs.ts`; new CLI `server/cortex-fs-cli.ts`; 4+5 new routes on
`server/index.ts`, all at KEAP's paths with KEAP's shapes.

**The load-bearing measurement.** A host daemon with the two-root list derives
the *exact* id set the container derives through the nested bind mount:

```
organ fs ids 167 · keap fs ids 167 · identical id sets: True · symmetric difference: 0
```

First pass and second pass against the live host tree (read-only):

| | pass 1 | pass 2 |
| --- | --- | --- |
| scanned | 167 | 167 |
| upserted | 167 | 0 |
| unchanged | 0 | 167 |
| removed | 0 | 0 |
| pruneRefused / emptyBodies / rootCollisions / rootsMissing | none | none |
| sentinel | ok | ok |

Composition, per root — the claim §0 made, now measured rather than inferred:

| root | spec | scanned | uids |
| --- | --- | --- | --- |
| `…/tenants/pazny/users` | `child-dirs` | **1** | akadmin, nos-docs |
| `…/tenants/pazny/shared/nos-docs` | `literal:nos-docs` | **166** | nos-docs |

Objects by user: `nos-docs` 166, `akadmin` 1. By type: `skill` 105, `page` 61,
`document` 1. By visibility: `shared` 166, `private` 1. Null body hash: 1 (the
PDF — not a `TEXT_EXT`, correctly bodyless). Degraded reads: 0.

The fixture suite (`server/fs-sync.test.ts`) is **26 cases, green**, in a
throwaway `mkdtemp` outside `nos_data_root`: two uids, canonical uid, the
literal-root id equality, visibility flip (and that it flips exactly once),
frontmatter/CRLF/strict-parse, dangling anchor, BODY_CAP, prune, move/rename,
**per-uid zero-scan**, global zero-scan, absent root, **cap**, EACCES, degraded
read with retry, and five sentinel cases. `MAX_FILES` gained an env override
purely so the cap guard is reachable from a test — a prune guard nobody has seen
fire is a guard nobody has tested. Full organ suite: **225 passing**.

### 10.3 Steps 6–7 — the feeders and the harness

`keap-consolidate.py` and `keap-embed-sync.py` are fan-out jobs; the diff
harness is new (`cortex-corpus-diff.py`, Pulse job on `cortex-base`, 05:30 UTC).
The fan-out's one genuinely dangerous part — the shared state ledger — is pinned
by **7 cases in `tests/anatomy/test_consolidate_fanout.py`**, driven against
throwaway HTTP sinks: both targets fed from one sweep, each target seeing only
its own token, second run a no-op, **a down target recording no state and not
failing the run**, the retry going to the failed target only, a down incumbent
being fatal, the v1 read-shim, and the budget counting swept items not POSTs.

First real harness run (live KEAP read-only + the local organ):

```
S2 diff — night 1 (agree streak 0/3)
  fs objects      167 vs 167   ids exact
  real user docs  1         <- the denominator that matters
  body hashes     match
  taxonomy        1841 vs 1841   PARITY
  onto1 digest    not served vs onto1:5d9bef3706a3c8ac   CEILING — keap 1.26.0 does not publish it
  captures        128 vs 1   DIFFER
  embeddings      pending 0 vs 0   (model nomic-embed-text/768 both — comparable)
  organ pass      pruneRefused False  emptyBodies 0  rootsMissing none  collisions 0  sentinel ok
  VERDICT         DISAGREE  (fs ids ok, body hashes ok, taxonomy ok, captures NO, embed shape ok)
  … NOT EXERCISED (9 items) …
  This run does not show that ingestion is correct. It shows that two
  near-empty corpora are equally near-empty.
```

**Body hashes match across all 167**, which is the §1.5 decision working: both
sides read the same published host tree, so the `--facts-json` divergence has no
opportunity to appear.

The captures clause is IN the verdict, and the first version of this harness had
it out — which produced a night that printed `captures 128 vs 1 DIFFER` and
still counted as agreement, advancing a 3-night clock. Captures are the only
signal here that measures the consolidator fan-out at all; without them a night
on which the second target was never fed would read green. Corrected before the
first night was recorded. Tonight's DISAGREE is the correct answer: the fan-out
has not run, and the single organ-side capture is a smoke POST.

The organ's embed pass was also exercised end to end against the new routes —
`keap-embed-sync` against the local organ upserted **3 225** vectors
(`taxonomy` 1 841, `note` 1 216, `object` 167, `capture` 1) at
`nomic-embed-text`/768, leaving pending at 0.

### 10.3b Step 7, second pass — the harness that adjudicates

The version above prints a red light. That is not what makes running two
builders worth more than migrating one into the other: **each corpus is a check
on the other**, so a difference should say *which side is wrong*. Rebuilt around
that, plus the per-table row counts and id sets §6.2 actually asks for.

**Three referees, none of which either corpus controls.** A verdict without one
is an opinion, and the harness publishes `unknown` rather than an opinion:

| referee | settles |
| --- | --- |
| the host filesystem (`os.stat`, read-only, never opens a file) | "the organ's reader missed it" vs "KEAP kept a row for a deleted file"; and for a row both sides hold with different `size`/`mtime`, **which side matches the bytes on disk** |
| `knowledge/canonical` at the pinned ref | a node in the pin + KEAP but not the organ = the organ's store was never re-materialised; the same node missing from KEAP = the **container** is behind the pin. Same shape, opposite culprit |
| `~/.nos/keap-consolidate-state.json` | a capture gap that is a job which never ran, not an ingestion defect |

**`GET /agent/v1/graph` was added to the organ** (KEAP's route, path and shape,
`ro`, all SELECTs) for one reason: without it the taxonomy could only be compared
on its COUNT — and **a count passes two different 1841-node trees as parity**.
KEAP has had the route all along; the organ was the missing half.

**23 verdict slugs, each with the evidence that picked it.** Four of them
resolve to *neither corpus is wrong*, and those are gated as hard as the real
defects — a harness that can only blame a corpus blames the wrong thing loudly:
`not-a-mirror-row` (a KEAP surface the organ does not serve),
`organ-pass-degraded` / `keap-pass-degraded` (a refused or truncated pass
explains a missing id by itself), `shared-uids-divergence` (one env var),
`fanout-never-ran`.

**Gate:** `tests/anatomy/test_corpus_diff_harness.py`, **40 cases**, offline and
hermetic — synthetic corpora, a `tmp_path` tree as the filesystem referee, plus
one end-to-end run of the real script over two throwaway `/agent/v1` daemons.
Mutation-checked: removing the degraded-pass pre-emption or inverting the
stale-reader naming turns it red.

**The first real run, and the four defects it found in the harness itself.**
Live KEAP read-only (`1.26.0`) + a local organ on spare port **8198** against a
**copy** of its store in `/tmp`. Nothing deployed, nothing written: KEAP's health
was byte-identical before and after (3 355 vectors, same `db_identity`), and
every mtime in the user tree pre-dates the session.

```
S2 corpus diff — night 1 (agree streak 0/3)
  keap 1.26.0   cortex 0.1.0
  real user docs   1         <- the denominator that matters
  referees         filesystem yes · canonical tree yes · feeder state yes

  table                        keap   organ    both  onlyK  onlyO   ids
  knowledge_objects             170     167     167      3      0   DIFFER
  knowledge_objects[fs:]        167     167     167      0      0   exact
  taxonomy_nodes               1841    1841    1841      0      0   exact
  taxonomy_metadata            1216    1216       —      0      0   —    (count only)
  api_taxonomy_metadata         128       0       0     50      0   DIFFER
  relations                     788     788       —      0      0   —    (count only)
  embeddings[capture]           128       0 · [note] 1216 → 0 · [object] 170 → 0 · [taxonomy] 1841 → 0
  embedded[object]              170    None  · embedded[taxonomy] 1841 None   (ref set NOT derived)
  corpus parity    NOT PINNED — the pinned tree has 2393 nodes; keap has 1750,
                   organ has 1750 (+91 generated, outside the referee), and 643
                   are in NEITHER. An 'exact' id set above is agreement on a
                   stale tree, not parity
  onto1 digest     not served vs onto1:5d9bef3706a3c8ac   CEILING
  VERDICT          DISAGREE (fs ids ok, body hashes ok, taxonomy ok,
                             captures NO, embed shape ok, embedded refs NO)

  [FEEDER ] fanout-never-ran ×1   keap 128 vs organ 0; the ledger is version 1
            with targets ['keap'] — the fan-out has never fed the organ. The
            corpora are not disagreeing; one was never written to.
  [ORGAN  ] organ-embed-behind ×2  cortex holds 0 object vectors for 167 sources
  [NEITHER] not-a-mirror-row ×3   type 'table', owner 'nos-agent', no fs: id
  [NEITHER] both-behind-pin ×1    643 pinned nodes in NEITHER corpus
  [NEITHER] outside-referee-jurisdiction ×1   91 nos.* nodes, generated
```

`fs ids exact` **and** `body hashes match` across all 167 — the §1.5 decision
working: both sides read the same published host tree, so the `--facts-json`
divergence has no opportunity to appear. `taxonomy exact` is now a real
statement about **1 841 ids**, not two equal counts.

The run's real value was the four things it found **in the harness**, all fixed
and gated before this record was written:

1. **`taxonomy 1841 vs 1841 PARITY` was a lie of omission.** Both sides agree —
   and both are behind the pin by 643 nodes. The referee was only consulted for
   ids that *differed*, so perfect agreement skipped it entirely, and the
   strongest-looking line in the report answered §4.4's question wrongly. Now
   there is a `corpus parity` line, and `both-behind-pin` is a finding. It is
   deliberately **not** a verdict clause: parity is currency, not agreement, and
   failing the 3-night clock for it would fail it for something the clock does
   not measure.
2. **A derived number that was wrong in a known direction.**
   `embedded = sources − pending` holds only while `pending` is complete.
   Truncated at the 500-item page cap it *overstates*, by exactly what the cap
   hid — the first run reported **1 341 of 1 841 taxonomy refs "embedded" against
   a store holding zero vectors**. Worse, `pending` is largest exactly when a
   side is furthest behind. The derived set is now withheld when the cap is hit,
   and the exact `byKind`-vs-sources row count carries the finding instead.
3. **`embedded refs ok` over a store with no vectors.** The clause keyed only on
   `only_in_*` findings, so when the ref-set diff was *skipped* the clause read
   green — the same "two silences compared equal" failure the onto1 digest rule
   already refuses. `count_mismatch` is now inside the clause.
4. **91 false accusations from a referee out of its jurisdiction.**
   `knowledge/canonical` is the source for the canonical taxonomy and nothing
   else; the estate self-model registers `nos.*` through `registerExtNode`.
   Judging those against the tree produced 91 × "fed from something this checkout
   is not pinned to". The fix is structural rather than a hardcoded prefix — a
   node is in jurisdiction when its ROOT segment is one the canonical tree
   defines — so the next generated subtree needs no remembering.

One honest wart, recorded rather than hidden: `GET /agent/v1/embeddings/pending`
runs `pendingEmbeddings()`, which **prunes** vectors whose source row is gone. It
is the only wire path publishing the model, the dimension and the pending diff,
so the harness calls it and then asserts the returned `pruned` is 0 — a non-zero
value is reported as `harness-side-effect`. A tool that writes while claiming not
to is worse than one that admits it.

### 10.4 Four things this build learned that the design did not know

1. **The pin is v1.34.0, not v1.32.1**, and v1.34.0 also populated
   `knowledge/ontology/relations/` (0 → 417 typed edges). Parity is a wider
   change than "re-sync canonical".
2. **The live KEAP container is v1.26.0** while the pin is v1.34.0, and it does
   **not publish an onto1 digest** on `/agent/v1/health`. The strongest
   available taxonomy check is therefore unavailable against the live incumbent
   today; the harness reports that as a stated CEILING and compares counts. Two
   missing digests are never allowed to compare equal.
3. **`users/nos-docs` enumerates as a uid contributing zero files** — it is the
   pre-created bind mountpoint. It is harmless only because the *other* root
   contributes 166 files for that same uid and `foundByUid` is global. Remove
   the shared root and the per-uid guard is the only thing standing between that
   empty mountpoint and the loss of the entire self-model.
4. **The organ's GDPR row had become false.** `cortex-base` said the service
   "holds NO per-user content and NO knowledge_objects corpus"; porting fs-sync
   ended that. The row now carries `user_documents` +
   `consolidator_datapoints`, `tenant_users` as a subject class, and a
   filesystem-driven retention rather than `0`.

### 10.5 One gate whose premise expired

`tests/anatomy/test_cortex_organ_contract.py` asserted `"pulse" not in manifest`
with the reason *"no pulse job before C2 (no embed surface exists)"*. That
premise is spent — the daemon serves the embed surface now. The assertion was
NARROWED rather than deleted, because the thing worth preventing was never "a
job", it was this plugin quietly becoming a writer: cortex-base must own exactly
`cortex-corpus-diff`, and that job must hold read-only tokens only. The two
feeders stay on keap-base as fan-out jobs — duplicating them here would sweep
the sources twice and give the shadow its own schedule to drift on.

### 10.6 Not done here, and deliberately

- **No converge, no deploy.** The role, plist, sentinel task, credentials and
  Pulse wiring are written and syntax-checked; the organ's live store is
  untouched and still carries the **pre-parity** materialisation (1 841 nodes).
  Re-materialising it is the first act of the deploy, and until it happens the
  taxonomy line above reads PARITY only because both sides are equally stale.
- **No nights.** Step 8 is calendar, and it cannot start before the deploy.
- **§1.8 (Bone's `state.db` inside the knowledge tree) remains flagged, not
  fixed**, exactly as instructed.

---

## S2 exit — decided 2026-09-03

**Decision (delegated by the operator, notification 382): S2 is CLOSED as
validated; S3 may begin; the nightly diff continues as a standing guard, not as
evidence-gathering.**

The evidence it rests on, from the ledger (`~/.nos/cortex-corpus-diff.json`):
39 nights, 35 agree / 4 disagree, `halted: false` throughout — the
removal-shaped class, the only one this plan treats as disqualifying, never
fired. Each disagreement, read one at a time: 07-27 `captures` (S2 standing
up), 08-18 + 09-02 `taxonomy` (import churn), 09-03 `embedded refs` — measured
same-day: the organ pass simply had not walked since that morning's doc churn,
and running fs-sync + embed-sync by hand returned `agrees: true` within the
hour. Every one was ingestion LAG on a cadence, none was divergence of content.

The caveat S3 inherits: corpora agree NIGHTLY, not intraday — a same-day
consumer of both sides must not assume coherence between 04:45 and the next
pass. The rule this section obeys is the notification's own: adding S2 nights
past the third disagreement is how a parallel run becomes permanent furniture.
S2 reported; this is the S3 decision it asked for.
