# Cortex S0 — Verification report

Stage: **S0 (Verify, blocking)** for `docs/plans/cortex-self-core.md`.
Run: 2026-07-26. Mode: **read-only** — nothing in either repo was changed; no
deploy, no converge, no container writes. Every number below carries the command
that produced it. Where a thing could not be measured, it says so.

---

## VERDICT

**YES — with amendments. S1 may proceed.**

The one STOP condition holds: **0 corpus rows lack an external source** (measured,
reproduced). The plan's load-bearing claim — "this is a migration of ownership,
not of data; the corpus can be rebuilt rather than copied" (§2, §8.2) — survives
verification. S2's parallel-rebuild strategy therefore does not need a real
migration.

Nothing S1 depends on is broken. S1 ("docs become knowledge") reads the §2
facts about corpus shape and the organ's `onto1` digest; both reproduced. The
digest `onto1:5d9bef3706a3c8ac` is confirmed.

Several numbers **moved**. None of them flip a decision — they change scope,
labels, or later-stage inputs, and are listed as amendments so a human need not
re-derive them:

- **UI API surface grew 54 → 69 routes (33 → 47 corpus-facing).** Larger S4
  scope; same approach. Amendment, not a blocker.
- **Default index cost is 160.6 KB/vec, not 153 KB/vec** (model under-predicts
  ~4.5 %). Makes §5 slightly *worse*, not better; the `float8` decision is
  unaffected. Amendment.
- **KEAP packed repo size is not reproducible from the host** (shallow clone at
  the wrong tag). The load-bearing part of that row — *no LFS* — is confirmed.
  Amendment.
- **"Single data chokepoint" is true for the connection, not for SQL issuance**
  — 27 raw `.prepare()` statements live outside `db.ts`, all in the DataTables
  modules. Matters for S4, not S1. Amendment.
- **The fs-sync coupling is real but mislocated:** it is in the compose mount
  stack, not `fs-sync.ts`. `/user-files` is a composite of two disjoint host
  subtrees, and `users/nos-docs` is empty on the host. S2 must reproduce the
  composition. Amendment to §8.2 — important for S2, does not block S1.

Two open items are correctly framed as *owed* already and stay that way:

- **Open question 2 (caller identity unlocks `kg:`/`ent:`)** — the S0 research
  slot that was meant to re-verify this returned a **null answer** ("Test").
  It was therefore **not re-confirmed this pass**. The plan's §8.1 static
  finding ("aspirational, owed rather than delivered") stands unchallenged and
  is already written as a promise-not-yet-kept — which is the required framing.
  No change needed beyond noting the re-verification did not run.
- **Open question 1 (explorer cache)** is answered by measurement: only
  `/api/graph` (1.92 MB, ~175 ms, rebuilt every call) warrants a cache, and the
  answer has a specific shape. Fold the finding into §8/§4.

---

## Fact table — plan value vs measured

| # | fact | plan value | measured | status |
|---|------|-----------|----------|--------|
| 1 | Corpus durable payload | ~11.5 MB (±50 %) | **11,896,936 B = 11.897 MB** (11.346 MiB) | reproduced (in band) |
| 2 | Corpus rows with **no external source** | **0** (must stay 0) | **0** (167 `fs:*` + 3 `table-*`; 128 captures all `source=app`/`origin=filesystem`) | **reproduced — STOP condition holds** |
| 3 | `keap.db` file | 565 MB | 565,846,016 B = **565.8 MB** (539.6 MiB) | reproduced (exact) |
| 4 | …of which vector index | 513.8 MB | 538,732,480 B = **513.8 MiB** (538.7 MB dec.) | reproduced (label MiB, not MB) |
| 5 | `embeddings_vec_idx_shadow` rows | 3355 | **3355** | reproduced |
| 6 | Embeddings | 3,355 · 9.8 MB | 3,355 rows · 10,306,560 B = **9.83 MiB** | reproduced |
| 7 | Bytes/vector (index) vs §5 model | model 153,600 B/vec | **160,575 B/vec** (=513.8 MiB / 3355); measured/model = 1.045 | **moved +4.5 %** |
| 8 | Organ ANN tuning | §5 "both" = 19.5 KB/vec | `ANN_DEFAULTS = {compressNeighbors:'float8', maxNeighbors:20}`; header records 65.6 MB / 3356 = **19.5 KB/vec** | reproduced |
| 9 | KEAP agent API surface | 49, ~40 corpus | **49** (agent.ts 47 + intake.ts 2); **~44 corpus**, 5 meta | total exact; **corpus +4** |
| 10 | KEAP UI API surface | 54, ~33 corpus | **69** (routes 61 + relations 4 + topics 4); **47 corpus**, 22 product | **moved +15 / +14** |
| 11 | `server/db.ts` | 2966 lines — single data chokepoint | **2966** lines; chokepoint holds for connection, **not** SQL issuance (27 raw prepares outside db.ts) | reproduced w/ caveat |
| 12 | Cortex organ digest | `onto1:5d9bef3706a3c8ac` | **`onto1:5d9bef3706a3c8ac`** (from store copy; daemon not running) | reproduced |
| 13 | KEAP repo LFS | no LFS, no `.gitattributes` | **confirmed** — no `.gitattributes`, no `filter.lfs`, `git lfs ls-files` empty | reproduced |
| 14 | KEAP repo packed size | 3.46 MiB packed | **not reproducible** — host clone is shallow at v1.26.0; nOS pins v1.32.1 | **unmeasurable** |
| 15 | fs-sync source path | `tenants/<slug>/users`, RO bind mount | path **exists, readable** as user `pazny`; near-empty (5 files, all Bone state) | reproduced w/ caveat |
| 16 | `nos_data_root` | `/Volumes/SSD1TB/nOS/data` (removable) | confirmed (`config.yml:201`); volume currently mounted | reproduced |
| 17 | fs-sync id derivation | `fs:<uid>:<sha1(relPath)[:16]>`, uid = dir name | confirmed (`fs-sync.ts:434-445,473`) | reproduced |
| 18 | fs-sync visibility | from config `SHARED_UIDS`, not fs perms | confirmed (`fs-sync.ts:479`, `:75-80`) | reproduced |
| 19 | `keap-features-sync` after 2026-07-26 fix | "now succeeds" | **unconfirmed** — 2/2 recorded runs FAILED (exit 255); fix `f5addeb7` landed ~6.5 h *after* last run; not re-fired since | **moved / pending** |

### Payload breakdown (fact 1)

`knowledge_objects` 87,686 B (170 rows) · `api_taxonomy_metadata` 47,316 B (128) ·
`taxonomy_metadata` 1,455,374 B (1,216) · `embeddings.vector` 10,306,560 B (3,355).
The mass is vectors (10.3 MB) + `taxonomy_metadata.data` (1.46 MB); the two text
corpora together are <135 KB.

### Embeddings by kind (fact 6)

taxonomy 1,841 (5,655,552 B) · note 1,216 (3,735,552 B) · object 170 (522,240 B) ·
capture 128 (393,216 B). All dim=768, model `nomic-embed-text`.

### Fact 2 — honesty caveat on "external source"

0 rows lack *any* external source. But the `fs:*` sources are **user files on the
removable external volume** `/Volumes/SSD1TB` (e.g. `fs:akadmin:…` → frontmatter
path `documents/pazny prvni pokus/FORMULAR_…pdf`), **not git**. They are
reproducible via fs-sync only while that volume is mounted. This is the §8.3
host-side-mount-guard gap, not a missing source — the count of rows with no
external source stays 0.

### Commands (representative)

```
# fact 1 (durable payload)
docker exec iiab-keap-1 node -e "const D=require('/app/node_modules/libsql');
  const db=new D('/data/keap.db',{readonly:true}); …SUM over the four tables…"
# fact 2 (no-source rows)
docker exec iiab-keap-1 node -e "…COUNT knowledge_objects id NOT LIKE 'fs:%' AND
  NOT LIKE 'table-%'  →0 ;  api_taxonomy_metadata NOT(source='app' AND
  json_extract(metadata,'$.origin')='filesystem')  →0"
# facts 3-6 in-container libsql readonly probe (host sqlite3 FORBIDDEN)
# fact 7   python3 -c 'print(538732480/3355, 50*768*4)'
# fact 9   awk '/app\.(get|post|put|delete|patch)\(/{c++}END{print c}' server/agent.ts →47
# fact 10  awk over routes.ts+relations-routes.ts+topics-routes.ts → 61+4+4=69
# fact 11  wc -l server/db.ts →2966 ; per-module awk '/\.prepare\(/' → tables 19, rustfs 6, migrations 2
# fact 12  cp -R ~/cortex/data /tmp/scratch; CORTEX_STORE_PATH=… npm run store:status
# fact 19  sqlite3 ~/wing/app/data/wing.db 'SELECT … FROM pulse_runs WHERE job_id LIKE "%keap%"'
```

Note: `server/agent.ts` / `intake.ts` are detected by `file(1)` as `data`
(non-text bytes), so GNU `grep` silently returns nothing; `awk`/`sed` read them
correctly. Any future re-measure of these must not trust a bare `grep`.

---

## The three research answers

### A. "Does a caller identity actually unlock `kg:`/`ent:`?" — NON-ANSWER

The S0 research slot for this returned literally `answer: "Test"`, evidence
`["test"]`. **It did not run.** This is the re-verification the plan's §8.1
expected; it was not performed. Consequence: the plan's *static* §8.1 finding —
organ contains zero references to Bone/JWKS/Authentik, `agentAuth` is one
self-asserted scope bit believed by nothing, so `kg:`/`ent:` stay refused until a
token-exchange / on-behalf-of mechanism is built — **is neither confirmed nor
refuted by S0**. It is already written in the plan as owed rather than delivered,
which is the correct framing, so no amendment is forced; but do not treat §8.1 as
"S0-verified". It is S0-*unverified* and should be re-run before S4.

### B. fs-sync per-user visibility and tenant scoping outside the container (Open Q3)

**Verified-in-code. The hidden coupling is NOT in `fs-sync.ts` — it is in the
compose mount stack.** As pure code, `fs-sync.ts` is portable and derives exactly
what the plan claims:

- **user_id** comes from the **path segment only** — `canonicalUid(rawDir)` over
  each top-level directory NAME (`fs-sync.ts:434-445`), hashed into the id
  (`:473`). fs-sync reads **no** `st.uid`/`getuid`/ownership anywhere; process
  identity and file ownership are irrelevant to attribution. A host daemon
  running as a real user gains nothing fs-sync consumes.
- **visibility** is **binary and from config** — `SHARED_UIDS.has(f.uid) ?
  'shared' : 'private'` (`:479`), `SHARED_UIDS` = env `KEAP_FS_SHARED_UIDS`
  (`compose:126` → `nos-docs`). The users pass can only ever emit `private` or
  `shared`; the richer `tier-*` vocabulary (`rbac.ts`) is honoured on READ but
  the users pass cannot PRODUCE it.
- **tenant scope** is **not derived in fs-sync at all** — KEAP has no tenant
  column. Tenant = the mount: one container = one tenant. Point a host daemon at
  a path spanning more than one tenant's `users/` and cross-tenant files collapse
  into one namespace with no code-level guard.

**The one real dependency — the composed namespace.** `/user-files` is TWO host
trees overlaid: `tenants/<slug>/users` (`compose:62`) plus a nested bind-mount of
`keap_selfmodel_root` (host `tenants/<slug>/shared/nos-docs`) onto
`/user-files/nos-docs` (`compose:70`). On the host, `tenants/<slug>/users/nos-docs`
is an **empty pre-created mountpoint** (`tasks/main.yml:27-34`); the self-model
content lives at a **different** host path. A host daemon reading
`tenants/<slug>/users` directly sees `nos-docs` as empty and the entire shared
self-model constellation disappears. **S2 must reproduce the composition
explicitly** — walk both host roots and label the second as the shared uid — or
the self-model breaks silently.

**Prune guards hold**, with mount-specific caveats: whole-root unmount →
no-op early return (`:424`); empty mountpoint → guard (c) refuses (`:545`);
partial EACCES / dropped sub-mount → `walkComplete=false` → guard (b) refuses
(`:534`); a dropped `nos-docs` nested mount → per-uid zero-scan guard holds it
back (`:550-580`). The guard converts a data-loss bug into a **silent-staleness**
bug: the self-model can never be pruned/refreshed through the host `users/` path
because its content is never at `users/nos-docs` on the host in the first place.
**Not covered:** macOS VirtioFS (see memory `backrest-spike-virtiofs-blocker`) can
enumerate a directory while file bodies read empty; `walkDir` would not return
false, `bodyOf` swallows the read error and the object is upserted with correct
size/mtime but an **empty body** — a content-fidelity failure a host daemon on a
VirtioFS mount can hit that the current Docker-Desktop-bind-mounted container
does not.

*Not measured here:* per-visibility object counts and how many objects belong to
`nos-docs` — runtime numbers not read this pass. The "empty on host" claim is
inferred from `tasks/main.yml` + `keap_selfmodel_root`, not from a live stat.

### C. What crossing the API costs the three.js explorer (Open Q1)

**Verified-in-code, warm, in-container over loopback with forged admin
forward-auth headers** (container runs `KEAP_TRUSTED_PROXY=1`; unauth → 401;
admin identity = largest payload). Source matched to the live container
(`v1.32.1`, `/Users/pazny/projects/knowledge-explorer-and-preserver`; the
`~/keap/src` checkout is `v1.26.0` and was **not** used). This is the in-process
baseline; the real `/agent/v1` path adds a Traefik forward-auth + network hop on
top.

Routes `/explore` actually calls (from source, not guessed): **GET `/api/graph`**
on load (`useExplorerData.ts:181`, staleTime 5 min); GET `/api/health` (global
poll); **GET `/api/graph/neighbors`** on node focus (`:195`); GET
`/api/taxonomy-metadata/{id}` on detail-panel open (`DetailPanel.tsx:172`).

| route | size | min/med/max ms | note |
|---|---|---|---|
| `/api/health` | 0.1 KB | 0.3 / 0.6 / 7.4 | negligible |
| **`/api/graph`** | **1968.2 KB (1.92 MB)** | **102.3 / 174.6 / 582.7** (n=12) | **the heavy one** |
| `/api/graph/neighbors` (l=25) | 6–8 KB | 7 / 21 / 636 | max = 1-time cold vector-index load |
| `/api/graph/neighbors` (l=50) | 16.5 KB | 12.7 / 19.5 / 66.3 | scales ~linear with limit |
| `/api/taxonomy-metadata/{id}` | 1.7 KB | 0.2 / 0.2 / 0.7 | negligible |

`/api/graph` composition (envelope-unwrapped): nodes 1841 = 1531.6 KB (78 %),
relations 3704 = 306.6 KB (16 %), links 1828 = 84.1 KB, objects 170 = 44.6 KB,
topics 6. `meta.layoutVersion = v1:f99c46a4f3fbc805`. The handler comment
(`graph.ts:126`) says one uncached pass is fine "at ~790 nodes" — the corpus is
now **1841 nodes + 3704 relations (>2×)** and still rebuilt **uncached every
request**. `neighbors` reads the anchor's STORED vector (`graph.ts:369`),
synchronous, **no live Ollama embed** — so S4 adds no embedding round-trip there.

**Verdict on the hop:** only `/api/graph` matters. It is the prompt's exact 2 MB
case — 1.92 MB at ~175 ms server-compute, rebuilt fresh every call, paid on every
cold load, every 5-min refetch, and every new viewer. Everything else is <17 KB
and <25 ms warm.

**What a cache must do (one cache, `/api/graph` only):** the payload is
per-viewer scoped — `getVisibleObjects` (`graph.ts:185`) RBAC-filters objects —
so a single global blob is wrong. But ~97 % of the payload (nodes+links+relations+
meta ≈ 1922 / 1968 KB) is **viewer-independent** taxonomy + baked layout +
overlay. The cache must **split**: memoize the viewer-independent skeleton once
(the ~175 ms of work), compose only the small per-viewer object layer (44.6 KB at
170 objects; scales with tenant object count) per request. Invalidation is cheap
and host-side (taxonomy write, layout rebake, feature/metadata sync).
`meta.layoutVersion` is already a content hash → a natural ETag; add
`If-None-Match` on layoutVersion+taxonomy-version so the 5-min refetch returns
**304** and skips the 1.92 MB transfer when nothing changed. No cache is warranted
for `neighbors` or `taxonomy-metadata`.

---

## AMENDMENTS — proposed edits to `docs/plans/cortex-self-core.md`

Each is a proposal only; the plan was not edited. Marked **[blocker]** /
**[amendment]** / **[note]**.

### §2 measured-present table

1. **[amendment] Line 68 — vector-index label is MiB, not MB.**
   `513.8 MB` → **`513.8 MiB (538,732,480 B ≈ 538.7 MB dec.)`**. Reproduced
   exactly; only the label was loose.

2. **[amendment] Line 71 — agent API corpus count.**
   `49 endpoints, ~40 corpus-facing` → **`49 endpoints (agent.ts 47 + intake.ts
   2), ~44 corpus-facing, 5 meta/reasoning`**. Total exact; corpus is +4.

3. **[amendment] Line 72 — UI API surface grew.**
   `54 routes, ~33 corpus-facing` → **`69 routes (routes.ts 61 + relations 4 +
   topics 4), 47 corpus-facing, 22 product-facing`**. This is the largest move.
   Also fix the re-measure hint: `grep '/api/' in server/*routes*.ts` **misses
   `server/fs-mappings.ts`**, which registers further `/api/fs/mappings/*` routes;
   the true glob must include it, so even 69 is a floor for the three named files.

4. **[amendment] Line 73 — "single data chokepoint" is half-true.**
   Keep `2966 lines`. Qualify: **`the single DB-connection owner, but not the
   single SQL issuer — 27 raw .prepare() live outside db.ts (tables.ts 19,
   tables-rustfs.ts 6, migrations.ts 2)`**. Consequence for S4: the
   taxonomy/objects/embeddings/relations/topics/captures/promotions/lint corpus
   all route through db.ts's function API (zero raw prepares), but **DataTables
   owns its 25 raw statements directly against `db.getDb()`** — so when the
   DataTables/`ent:` registry moves (§6b), its SQL moves with the tables modules,
   not through the chokepoint.

5. **[amendment] Line 74 — packed repo size is not host-reproducible.**
   `3.46 MiB packed, no LFS` → **`no LFS (confirmed); packed size unmeasured —
   host clone ~/keap/src is a shallow graft at v1.26.0, nOS pins v1.32.1`**. The
   taxonomy grew 1750→2393 between those tags, so a full clone at the pinned tip
   is larger than both the shallow reading (2.16 MiB pack + 896 KiB loose) and
   the plan's 3.46 MiB. The load-bearing fact (no LFS) holds; the MiB does not.

6. **[note] Line 66 / §2 finding — sharpen the "external source" claim.**
   0 rows lack a source **stays true**, but the sources are user files on the
   removable volume, not git. Suggest appending to the line 80-83 finding: *"…and
   the external sources are the removable user volume, not git — reproducible via
   fs-sync only while `/Volumes/SSD1TB` is mounted (see §8.3)."* This keeps the
   ownership-not-data conclusion while removing any implication that the corpus
   is git-rebuildable.

7. **[note] fs-sync source is present but near-empty.** The `users/` tree
   currently holds only 5 files (Bone `.face/state.db` + `.DS_Store`), no user
   documents. Worth a parenthetical at line 75 so S2 does not read "source
   exists" as "source has content".

### §5 scale

8. **[amendment] Lines 149 & 153 — default index cost is higher than the model.**
   Measured **160,575 B/vec (156.8 KiB)**, not 153 KB; measured/model = 1.045
   (per-node own-copy + neighbour-id list + shadow page overhead). Update:
   `That is the whole 153 KB/vector` → **`~160 KB/vector`**; the default-row
   `153 KB / ~153 GB` → **`~160 KB / ~160 GB`**. This makes §5 slightly *more*
   alarming, not less — the direction supports S3's premise; only the arithmetic
   was optimistic. The `float8` / `max_neighbors` reasoning and the `19.5 KB/vec`
   "both" row are unchanged (organ `ANN_DEFAULTS` confirmed).

### §6 roadmap

9. **[amendment] Line 256 (S4) — corpus route count.**
   `the KEAP UI's ~33 corpus routes` → **`~47 corpus routes`** (see amendment 3).

10. **[note] Line 200 (S0 exit) — digest verified against a store copy.**
    The cortex daemon is **not running** (no launchd plist, nothing on 8098). The
    digest was reproduced by copying `~/cortex/data` to scratch and running
    `store:status` against the copy (live store untouched, scratch removed).
    Also record the two-digest distinction from `cortex-store.ts`: the
    conformance/port-fidelity gate uses `onto1:76d1f3ad728b382b` (materialise=
    false, 790-node reference); the operational estate store is
    `onto1:5d9bef3706a3c8ac`. The plan's value is the operational one and holds.

### §8 open questions

11. **[amendment] Q1 (line 410) — answered, and the route count is wrong.**
    Replace with the §C finding: only `/api/graph` (1.92 MB, ~175 ms, rebuilt
    uncached every call) warrants a cache; the answer is **yes, one split cache** —
    memoize the viewer-independent skeleton (~97 %), compose the per-viewer object
    layer per request, ETag on `layoutVersion` for a 304 on the 5-min refetch.
    Fix "~33 UI routes" → "~47". Everything else the explorer calls is <17 KB /
    <25 ms and needs no cache.

12. **[amendment] §8.2 (lines 439-455) — the coupling is real, just relocated.**
    §8.2's core claim (host daemon derives the same ids/visibility for the
    `users/` tree) is **confirmed**. But add the compose-mount finding (§B):
    `/user-files` is a composite of two host subtrees; `tenants/<slug>/users/
    nos-docs` is an **empty mountpoint** on the host and the self-model content
    lives at `keap_selfmodel_root` (`shared/nos-docs`). So the line "the two id
    sets should match **exactly**" (line 449) is only true **if S2 reproduces the
    composition** — a naive host walk of `users/` will MISS the entire shared
    self-model and the id sets will NOT match. Amend S2's exit (line 236,
    "within a stated tolerance") to reconcile with §8.2's "exactly" and add:
    *"S2 must walk both host roots (`users/` and `shared/nos-docs`) and label the
    second as the shared uid; and must guard against VirtioFS empty-body reads,
    which fs-sync's prune guards do not catch."*

13. **[note] Q2 / §8.1 — re-verification did not run.** The S0 research slot for
    "does caller identity unlock kg:/ent:" returned a null answer. §8.1 already
    frames the capability as aspirational/owed, which is correct and needs no
    text change — but it should not be cited as "S0-verified". Recommend a one-
    line stamp: *"§8.1 not re-verified in S0 (research slot returned null); re-run
    before S4."*

### Out-of-plan operational note (not a §-edit)

14. **[note] `keap-features-sync` is fixed-but-unproven.** Commit `f5addeb7`
    (2026-07-26 11:42 UTC) set the script `100755`; the exec bit is confirmed in
    git and on disk, matching its three green siblings. But both recorded runs
    (last 2026-07-26 05:02 UTC, ~6.5 h **before** the fix) FAILED exit 255
    (`Permission denied`), and the job has **not re-fired since**. Success is
    **unconfirmed** until the next daily fire (`0 5 * * *` → ~2026-07-27 05:04
    UTC). The other three KEAP Pulse jobs (`keap-consolidate`, `keap-embed-sync`,
    `keap-lint`) are 2/2 green.

---

## Read-only compliance

No writes to either repo. No ansible/converge/docker-restart/container writes.
The live KEAP libSQL DB was probed **in-container with node readonly** only (host
`sqlite3` never touched it). The cortex digest was read from a **copy** of
`~/cortex/data` in a scratch dir (removed after). Wing's plain-SQLite `wing.db`
was read read-only. The only file written is this report.
