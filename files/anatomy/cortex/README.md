# files/anatomy/cortex/ — the Cortex organ (vendored port)

**Status:** P-4 build-sequence steps 1–8 landed. The store is wired and
materialises itself from git, the ANN index is at its measured tuning, the onto1
digest gate is **green and pinned**, and the **daemon serves the validate surface
on `127.0.0.1:8098`** with 15 Playwright tests green against the built bundle. No
Ansible role yet (step 9), **nothing deployed**.

Cortex is the nOS reasoning organ — the fourth brain beside Bone (signals), Wing
(observes) and Pulse (keeps time). It is a **verbatim port** of KEAP v1.27.0's
`cortex-*` modules. See `docs/plans/nos-cortex-organ-design.md` at the repo root
for the full design and the 13-step build sequence.

## The one rule: PORT, NOT REWRITE

The `onto1` ontology digest and the `cx1` opcode-registry hash are computed
**independently on both sides** and compared. If this tree and the KEAP tree
disagree by one byte in the wrong place, the digests diverge and the two halves
**silently reject each other's ASTs** — a `binding` drift rejection, not a crash.

Therefore:

- Every file under `server/`, `shared/`, `src/game/`, `knowledge/` is a
  **byte-identical copy** of its KEAP counterpart. Verified by sha256 at port time.
- The KEAP-relative directory layout is mirrored exactly (`server/`, `shared/contracts/`,
  `src/game/data/`) **so that zero import paths need rewriting**. The design doc
  budgeted "import-path rewrites only" for `cortex-resolve.ts` /
  `cortex-ontology-version.ts` / `cortex-validate.ts`; mirroring the layout spent
  none of that budget. Keep it that way — a re-sync from KEAP should stay a plain
  `cp`/`diff`, never a patch.
- `src/game/` looks out of place in an organ with no game. It is the taxonomy
  dataset's KEAP home and it stays there for the reason above.
- **Never run a formatter, linter, or whitespace normaliser over `server/db.ts`.**
  It contains two literal NUL bytes inside the `relationId` hash template
  (KEAP `server/db.ts:2567`). `grep` treats the file as binary; a normalising pass
  would silently change the hash inputs.
- `server/migrations.ts` and `server/taxonomy.ts` are whole files, not subsets.
  Dropping a migration changes the `establishDbIdentity` backdate; subsetting
  `taxonomy.ts` breaks the onto1 §2.2 fixpoint and §2.3 existing-id-wins traps.

## What is here

| Path | Source | Lift |
|---|---|---|
| `shared/contracts/cortex.ts` | KEAP `shared/contracts/cortex.ts` | verbatim |
| `server/cortex-opcodes.ts` | KEAP `server/…` | verbatim |
| `server/cortex-lang.ts` | KEAP `server/…` | verbatim |
| `server/cortex-resolve.ts` | KEAP `server/…` | verbatim |
| `server/cortex-ontology-version.ts` | KEAP `server/…` | verbatim |
| `server/cortex-validate.ts` | KEAP `server/…` | verbatim |
| `server/db.ts` | KEAP `server/…` | verbatim (whole file) |
| `server/migrations.ts` | KEAP `server/…` | verbatim (whole file) |
| `server/rbac.ts` | KEAP `server/…` | verbatim — required by `db.ts`, omitted from design §4 |
| `server/tokens.ts` | KEAP `server/…` | verbatim — the bearer tiers; sha256 → `timingSafeEqual`, never `===` |
| `server/build-version.ts` | KEAP `server/…` | verbatim — `/health`'s `version` |
| `server/taxonomy.ts` | KEAP `server/…` | verbatim (whole file) |
| `src/game/{data,types}/taxonomy.ts` | KEAP `src/game/…` | verbatim — the 790-node spine |
| `server/*.test.ts` | KEAP `server/…` | verbatim — 83 + 54 + 4 = 141 tests |
| `knowledge/onto1-{compose,conformance}.mjs` | KEAP `knowledge/…` | verbatim |
| `knowledge/{_ontology,ingest,spine-render}.mjs` | KEAP `knowledge/…` | verbatim — the git materialisation path |
| `knowledge/{spine,canonical,ontology}/`, `knowledge/fixtures/onto1/` | KEAP `knowledge/…` | verbatim — the git SoT itself |
| `scripts/ann-recall.mjs` | KEAP `scripts/…` | verbatim |
| `docs/specs/*.md` | KEAP `docs/specs/…` | verbatim — the normative specs the modules cite by § |

Locally authored (the only non-ported files): `server/index.ts`,
`server/cortex-{config,ann,store,store-cli}.ts`, `server/cortex-store.test.ts`,
`server/onto1-digest.test.ts`, `server/tokens.test.ts`, `e2e/organ-boot.spec.ts`,
`scripts/ann-corpus.mjs`, `package.json`, `tsconfig.json`, `tsconfig.server.json`,
`vitest.config.ts`, `playwright.config.ts`, `.gitignore`, `VERSION`, this README.
`e2e/validate.spec.ts` is a port with **four documented deviations**, listed in
its own header and summarised under "The daemon" below. `tsconfig.server.json`'s `compilerOptions` are
byte-identical to KEAP's — a divergence there means the two repos typecheck the
same source differently.

### Known vendor drift (as of 2026-07-25)

The port ref was KEAP `dev` @ `264cc22`. KEAP `dev` has since moved to `c880f03`,
and **one commit touches the vendored set**: `273de0e` *"docs(schema): name
object_type_definitions as dead schema at its DDL"*.

| file | drift |
|---|---|
| `server/migrations.ts` | +23 lines of SQL `--` comment inside migration 001's `object_type_definitions` DDL |
| `docs/specs/cortex-validate.md` | one line citation repointed, 60 → 83 |

Both are comment-only: no statement changes, no schema change, no effect on the
`onto1` digest or the `cx1` registry hash. The vendor pin has deliberately NOT
been bumped here — moving it is a scope decision, not a side effect of a store
stage. Re-syncing is the usual plain `cp` of those two files.

## Verifying the port

```sh
nvm use 22                 # Node 22 + npm 10. NOT npm 11 — it writes a lock npm 10 rejects.
npm ci
npm run typecheck          # strict, clean
npm test                   # 193 tests (141 ported + 26 store/ANN + 19 digest gate + 7 tokens)
                           #   — includes the 6 onto1 fixtures, run as a child process
npm run conformance        # the same 6 fixtures, standalone
npm run spine:check        # knowledge/spine/*.json ≡ the generated src/game/data/taxonomy.ts
npm run build              # tsc -p tsconfig.server.json && esbuild → dist-server/index.js
npm run test:e2e           # 15 Playwright tests against the BUILT bundle (build first)
```

### The digest gate (build sequence step 5 — THE HARD GATE)

On a **freshly initialised** store (790 spine nodes, 16 seed verbs, zero
`taxonomy_nodes_ext` rows) `cortexOntologyVersion()` must return
**`onto1:76d1f3ad728b382b`**.

Three files assert it, from three different directions, and they are not
redundant:

| file | axis | what a failure means |
|---|---|---|
| `server/onto1-agreement.test.ts` | *ported, verbatim* — runtime **vs** the git reference, RELATIVE | the two implementations diverged from each other |
| `server/onto1-digest.test.ts` | *local* — both **vs** the literal, ABSOLUTE | the port diverged from KEAP's deployed validator |
| `server/cortex-store.test.ts` | *local* — the organ's **own boot path**, end to end | `openStore()` does not produce the graded state |

The agreement test alone is not enough: it is a relative proof, and a port that
had moved the reference implementation and the runtime the same way would still
pass it. `onto1-digest.test.ts` supplies the literal, asserts the input state
**first and separately** (so a state mismatch reads as "wrong state", not
"broken port"), and proves the digest is a function of its input rather than a
constant — a rename, a re-parent, a verb-label edit and a registered grown row
each move it; a dropped row and an agent-planted `proposed` verb each do not.

**Measured caveat, and the reason the fixtures are a separate gate:** all 790 seed
ids are ASCII, no seed name carries a non-ASCII character, and `localeCompare`
happens to agree with code-unit order on this exact id set. So §3.1 collation and
§3.3's UTF-8 requirement are **not discriminated at real-tree scale** — an
implementation that got both wrong would still reproduce this digest.
`case-05-verbs` and `case-06-unicode-and-tabs` are what catch those. That is why
`onto1-digest.test.ts` runs `knowledge/onto1-conformance.mjs` as a child process:
`npm test` fails if any of the six fixtures fails, instead of the edge rules
riding on someone remembering to type `npm run conformance`.

Verified against KEAP directly, not only against the vendored copy: KEAP `dev`
@ `c880f03` composes the **byte-identical** 806-line / 29 396-byte canonical
string (`sha256 76d1f3ad728b382bb4c56659d92af06524ca23aab5ec6f19d90f23de3742c7de`,
of which the digest is the first 16 hex).

A **materialised** store (below) carries 1750 nodes and a different, larger
digest. That one is a statement about the **corpus**, and it is the value that
must agree with KEAP's live digest at cutover for ASTs to bind. Neither number is
wrong; grading one against the other is.

## The store (build sequence step 4)

```sh
npm run store:init         # create/open the store, no ingest — the fresh-digest shape
npm run store:materialise  # + run the git ingest path, then tune the ANN index
npm run store:status       # facts about the store as it stands
```

Config: **`cortex_store_path`** (env `CORTEX_STORE_PATH`), default `~/cortex/data`,
matching `bone_runtime_dir: ~/bone`. **`KEAP_DATA_DIR` is not consulted.** It was
briefly, "so the vendored tests keep working untouched" — but those tests
(`server/cortex-resolve.test.ts:20`, `onto1-agreement.test.ts:37`,
`onto1-digest.test.ts:70`) set `KEAP_DATA_DIR` and import `server/db.ts`, which
reads the variable itself; none of them goes through `resolveStoreConfig`. The
fallback protected nothing and aimed an unconfigured organ at KEAP's data
directory. `openStore()` still *sets* `KEAP_DATA_DIR` from the resolved
directory — that is how the vendored `db.ts` and `ingest.mjs` are pointed at the
organ's store. The flow is one way.

**The store file is `keap.db`, not `cortex.db`.** Design §3 wrote `cortex.db`;
`server/db.ts:30` and `knowledge/ingest.mjs:60` each independently join the
basename onto a directory env var, so renaming it means patching two vendored
files forever. `cortex_store_path` therefore names the **directory**, which is
what actually isolates the organ. This is not the shared `keap.db` that
`cortex-full-scope-decision.md` forbids — different directory, different file,
different `db_identity`, and `cortex-store.ts`'s `assertClaimable()` **refuses to
open a store file the organ did not create**, which is that rule made mechanical
rather than aspirational.

That guard runs on the **filesystem, before `initDb()`** — bytes on disk plus the
`.cortex-store.json` marker, no SQL and no connection. It has to: `initDb()` sets
`journal_mode = WAL`, execs the schema, runs `runMigrations()` and INSERTs a
`db_identity`, so a guard placed after it can only *report* the write it exists
to prevent. Bytes-on-disk is also the only discriminator that is immune to the
schema question — a row count over hand-picked tables reads a foreign database
whose content lives elsewhere as "empty" and claims it. After `initDb()`,
`assertOwnStore()` handles the half a filesystem cannot: marker present but
`db_identity` changed ⇒ the file was **replaced**.

### What git materialises, and what it does not

| layer | git source | lands in |
|---|---|---|
| spine, 790 nodes | `knowledge/spine/*.json` → `spine-render.mjs` → the checked-in `src/game/data/taxonomy.ts` | `taxonomy_fts` (never rows) |
| delta, 960 ext nodes | `knowledge/canonical/**.json` (107 files, 1750 node records) via `knowledge/ingest.mjs` | `taxonomy_nodes_ext`, `node_descriptions`, `taxonomy_metadata`, `knowledge_imports` |
| ToE edges, 4434 | same canonical files | `concept_relations` → mirrored to `relations` by `syncToeRelations()` each boot |
| verbs, 16 | `knowledge/ontology/relation-types.json` + `RELATION_TYPE_SEED` (identical sets) | `relation_types` |
| **corpus** | **none — no git source** | **not materialised. `knowledge_objects` stays empty; it is C2 scope and no cortex module reads it.** |

`ingest.mjs` runs as a **child process** (it is a script that opens its own handle
and closes it), after `initDb()` because it does not create the tables it writes.
It is idempotent via the `knowledge_imports` sha markers — a second
`store:materialise` applies 0 files and lands the identical digest.

## The ANN index (build sequence step 6)

`server/db.ts:330` creates `embeddings_vec_idx` with **default** parameters — the
514.6 MB-for-3356-vectors shape measured in `docs/specs/durability-and-integrity.md`
§4. `server/cortex-ann.ts` retunes it to `compress_neighbors=float8` +
`max_neighbors=20` after `initDb()`, **without editing `db.ts`**, which works
because of four verified properties:

1. `DROP INDEX` takes the `_shadow` tables with it.
2. Re-creating with parameters **reindexes rows already present** — the retune is
   not a wipe.
3. `sqlite_master.sql` records the parameters, so live tuning is checkable.
4. Re-running db.ts's own `CREATE INDEX IF NOT EXISTS …(libsql_vector_idx(vector))`
   over an already-tuned index is a **no-op that preserves the parameters**.

(4) is load-bearing: it means `initDb()` cannot silently revert the store to the
514 MB shape on the next boot. `cortex-store.test.ts` pins it.

Degradation is preserved end-to-end: no vector layer ⇒ `outcome: 'unavailable'`,
FTS and the tree still materialise, the boot does not fail. A *rejected* tuned DDL
restores db.ts's default index rather than leaving the store index-less.

### Measured, 2026-07-25, 3356 × 768-d, k=10, 200 queries

`npm run ann:corpus -- --out /tmp/v.json` then `npm run ann:recall -- --vectors /tmp/v.json`.

| variant | shadow | build | µs/query | recall@10 |
|---|---|---|---|---|
| default (db.ts as shipped) | 514.6 MB | 47.7 s | 12370 | 99.80% |
| `float8` | 224.5 MB | 23.5 s | 7525 | **99.95%** |
| `max_neighbors=20` | 209.8 MB | 15.9 s | 4930 | 94.10% |
| **`float8` + `mn=20` (shipped)** | **65.6 MB** | **5.7 s** | **2270** | **94.25%** |
| `float1bit` | 41.0 MB | 7.7 s | 4870 | 72.20% |
| CONTROL `mn=3` | 41.0 MB | 2.8 s | 860 | 21.10% |

The size and build columns reproduce `durability-and-integrity.md` §4 **exactly**,
which is what makes the recall column trustworthy. The CONTROL at 21.1% proves the
harness discriminates.

**Design §3's "recall@10 = 100%" does not reproduce, and the number should be
retired.** It was measured on near-orthogonal random vectors — the corpus shape
`durability-and-integrity.md` §4 itself warns about, because there "10 results
returned" says nothing about *which* 10. On a clustered corpus (`ann-corpus.mjs`,
120 centroids, gaussian spread, L2-normalised) the shipped tuning scores
**94.25%**. The *decision*
still holds (8× smaller, 5× faster, and `float1bit` is decisively disqualified at
72.2%), but note the cost is carried by `max_neighbors=20`, not by compression:
`float8` alone scores 99.95% at 224.5 MB. If ~94% recall@10 is ever judged too
expensive, that is the fallback, and it is still 2.3× smaller than today.

## The daemon (build sequence steps 7 and 8)

`server/index.ts` → `dist-server/index.js`. It boots by calling `openStore()` —
steps 4 + 6 unchanged — then serves **four routes and no others**, bound to
`127.0.0.1:8098` (`CORTEX_BIND_HOST` / `PORT` | `CORTEX_PORT` override).

```sh
npm run build && npm start        # or: PORT=8098 CORTEX_STORE_PATH=~/cortex/data node dist-server/index.js
```

### What is mounted

| route | auth | source |
|---|---|---|
| `GET /health` | none | local — the organ's probe name (design step 12) |
| `GET /agent/v1/health` | none | the same handler at KEAP's path |
| `POST /agent/v1/validate` | `agentAuth('ro')` | lifted from KEAP `server/agent.ts:1197-1206` |
| `GET /agent/v1/validate/opcodes` | `agentAuth('ro')` | lifted from KEAP `server/agent.ts:1213-1219` |

Everything else is a **404 in the `{success:false, error}` envelope**, including
every other `/agent/v1/*` path KEAP serves (taxonomy, search, objects, relations,
tables, fs, lint, captures, curator, topics, embeddings, `openapi.json`), the
whole `/api` + SPA surface, and the `/ingest/v1` device tier. An express default
HTML 404 would read like a server fault to a caller that simply came to the wrong
organ.

**Explicitly NOT built here**, though design §7 step 7 names them: the new
`/agent/v1/context` recall endpoint, and the **Bone audit emit** per
validate/recall call. Both are additions rather than ports — `context` has no
KEAP counterpart to lift, and the audit path needs Bone's middleware, which is
step 9 territory. Neither is stubbed: there is no dead route and no silent
no-op emitter to mistake for a working one later.

### Auth: fail closed, and never `===`

`agentAuth` is KEAP `server/agent.ts:63-81`, behaviour for behaviour:

1. **Neither token configured ⇒ 503 for the whole surface**, checked *before* the
   bearer is even read. An unconfigured agent surface is a DISABLED surface, not
   an open one, and a caller cannot distinguish "wrong token" from "surface off".
2. `tokenEquals` (`server/tokens.ts`, verbatim) hashes both operands to sha256
   and compares with **`crypto.timingSafeEqual`**. The hashing is not decoration:
   `timingSafeEqual` *throws* on a length mismatch, so comparing raw tokens would
   turn a wrong-length token into a 500 where a right-length one is a 401 — an
   oracle for the secret's length, delivered through the error channel.
   `server/tokens.test.ts` pins this **structurally**, because `return a === b`
   passes every behavioural assertion there is. That is the whole reason the port
   instruction singles this file out.
3. RW satisfies an `ro` requirement; `ro` does not satisfy `rw`.

Rule 1 means **nothing runs in front of `agentAuth`**, and that includes the JSON
body parser. `express.json()` is mounted on the `validate` route *behind* the
auth middleware rather than app-wide, because a body-parser `SyntaxError` is an
error rather than a response: it skips every ordinary handler and lands in
express's built-in final handler, which answers `text/html` carrying the full
stack whenever `NODE_ENV !== 'production'` — which no deployment of this organ
sets. A truncated JSON body with **no** `Authorization` header, against a daemon
with **no** tokens configured, therefore used to return a stack trace with
absolute host paths where the contract promised a 503. Parsing after the bearer
check means an unauthorised body is never read. A four-argument error handler
sits below the 404 as the backstop; it answers in the `{success,error}` envelope
and discloses only the status and body-parser's `type` token.

`/health` deliberately still answers when the surface is disabled, reporting
`surface: "disabled"`. A liveness probe that 503s for want of a token would make a
correctly fail-closed organ indistinguishable from a dead one.

`CORTEX_TOKEN_RO` / `CORTEX_TOKEN_RW` are aliased onto the `KEAP_AGENT_TOKEN_*`
names `tokens.ts` reads (`aliasTokenEnv`, `server/index.ts`). That alias exists
**only** so `tokens.ts` stays byte-identical while the Ansible role gets to use
the organ's own vocabulary (`cortex_ro_token` / `cortex_rw_token`, design §2).

### `/health` and the three drift axes

Beside KEAP's nested `ontology.version` and `database`, the body carries a
`binding` block — `{ontologyVersion, databaseId, opcodeRegistryHash}`, the same
three axes stamped into every `ast.binding`, published where an operator, the
step-12 verify and Wing can read them without POSTing a program.
`e2e/validate.spec.ts` asserts the block equals the AST's, so it cannot become a
second, drifting copy of the same three facts.

`contracts` declares `cortex` **only**. KEAP's health also declares
`selfmodel: 1`; this organ serves no slug-tree surface, and declaring a contract
you do not implement is worse than declaring nothing.

### The one hazard worth knowing about

`server/db.ts:29-30` resolves its data directory **at module load**, and
`openStore()` is what sets `KEAP_DATA_DIR`. ESM evaluates every static import
before any top-level statement, so a static `import … from './cortex-validate'`
in `index.ts` would drag in `./db` and bind the wrong directory before `main()`
ran. **Every cortex module is therefore imported dynamically, after
`openStore()`.** esbuild preserves that laziness in the bundle (each becomes an
`__esm(...)` thunk).

The failure mode is silent: the daemon would boot, mint an identity in
`$PWD/data/keap.db`, answer every request plausibly, and report the configured
path it never opened. So `e2e/organ-boot.spec.ts` asserts against the
**filesystem** — the store file exists where it was configured, and
`.cortex-store.json`'s identity equals the one `/health` serves. Verified by
mutation: adding a static `import './db'` fails that test **and passes all
twelve ported ones**.

### e2e (step 8) — 15 tests, against the built bundle

`npm run test:e2e` builds nothing; run `npm run build` first. The suite boots
`node dist-server/index.js` (never `tsx`) against a throwaway `e2e/.data`, so the
artifact under test is the artifact a host would run.

The store is **not materialised**, on purpose. That gives 790 spine nodes and 0
ext rows — the same input state KEAP's own e2e runs against, so the ported
late-binding assertions (`tax:node[Kinematics]` → `01.01.01.01`,
`tax:node[motion]` → ambiguous with 4 candidates) are claims about the *same*
tree on both sides. It is also the state the pinned digest is defined for, so
every `ast.binding` in the suite carries **`onto1:76d1f3ad728b382b`**.

| file | tests | lift |
|---|---|---|
| `e2e/validate.spec.ts` | 12 | ported from KEAP, **four documented deviations** |
| `e2e/organ-boot.spec.ts` | 3 | local — boot order, fail-closed, nothing-else-mounted |

The four deviations, all in that file's header: the `contracts.selfmodel === 1`
assertion becomes an assertion of its *absence* (with its census note dropped);
`ast.binding` is additionally compared against `/health`'s `binding` block; and
the ontology digest is additionally checked against the pinned literal, not only
against `/^onto1:[0-9a-f]{16}$/`. Nothing else was reworded — an assertion
rewritten in transit stops being evidence that both implementations answer the
same.

## Not done yet

- **Step 11 (CI)** — the digest and conformance gates are now both inside
  `npm test`, so the step-11 `cortex` job inherits them; what remains is the job
  itself, the `tests/anatomy/` pytest shim, and adding the shared conformance
  gate to the retained KEAP repo's CI (KEAP-side, a separate PR).
- **`/agent/v1/context`** and the **Bone audit emit** — the two parts of design
  §7 step 7 that are additions rather than ports. See "What is mounted" above.
- **Steps 9–13** — Ansible role, plugin, CI jobs, blank verify, KEAP cutover.
  For the role: `cortex_store_path` defaults to `~/cortex/data`, the build step
  needs `npm run store:materialise` after `npm ci`, and `~/cortex/data/` must be
  added to the host-daemon restic set (design §7.6). The ANN and FTS indexes are
  regenerable and can be excluded from the snapshot. Two daemon-specific notes
  for that role: **set the launchd/systemd working directory to the organ root**,
  because `server/build-version.ts` (verbatim) reads `process.cwd()/package.json`
  and otherwise reports `unknown`; and the unit boots with
  `CORTEX_MATERIALISE_ON_BOOT` **unset**, so materialisation stays a build step
  and a restart never re-walks 107 canonical files before answering a probe.
- **Embeddings.** The store's `embeddings` table is empty and will stay so until
  the Pulse job `keap-embed-sync` runs (step 10) — the embedder is deliberately
  outside the organ. Until then `npm run ann:recall` must be fed a synthetic
  corpus (`npm run ann:corpus`); afterwards use `--from-store` and re-measure.

## Two design-doc intents that are dead

Both are written as live intent in `docs/plans/nos-cortex-organ-design.md` §3/§7 and
both were overturned by KEAP `docs/specs/cortex-full-scope-decision.md`
("Two corrections", vendored here):

1. **No `db_identity` carry-over.** The organ mints its own UUID on first boot.
   Adopting KEAP's would make the "is this the same database?" answer a lie on day
   one. Bindings carry a TTL (900 s default), so the blast radius is one TTL of
   rejections — and a rejection is the mechanism working.
2. **No shared `keap.db`,** not even read-only, not even transitionally. A reader
   cannot build its own tuned ANN index in a file it does not own.
