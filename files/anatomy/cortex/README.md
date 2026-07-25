# files/anatomy/cortex/ — the Cortex organ (vendored port)

**Status:** P-4 build-sequence steps 1–3 landed. Pure half green. Store NOT wired,
daemon NOT stood up, no Ansible role yet.

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
| `server/taxonomy.ts` | KEAP `server/…` | verbatim (whole file) |
| `src/game/{data,types}/taxonomy.ts` | KEAP `src/game/…` | verbatim — the 790-node spine |
| `server/*.test.ts` | KEAP `server/…` | verbatim — 83 + 54 + 4 = 141 tests |
| `knowledge/onto1-{compose,conformance}.mjs` | KEAP `knowledge/…` | verbatim |
| `knowledge/spine/`, `knowledge/fixtures/onto1/` | KEAP `knowledge/…` | verbatim |
| `docs/specs/*.md` | KEAP `docs/specs/…` | verbatim — the normative specs the modules cite by § |

Locally authored (the only non-ported files): `package.json`, `tsconfig.json`,
`tsconfig.server.json`, `vitest.config.ts`, `.gitignore`, `VERSION`, this README.
`tsconfig.server.json`'s `compilerOptions` are byte-identical to KEAP's — a
divergence there means the two repos typecheck the same source differently.

## Verifying the port

```sh
nvm use 22                 # Node 22 + npm 10. NOT npm 11 — it writes a lock npm 10 rejects.
npm ci
npm run typecheck          # all 15 TS files, strict, clean
npm test                   # 141 tests
npm run conformance        # 6 onto1 fixtures
```

The digest gate: on a **freshly initialised** store (790 spine nodes, 16 seed
verbs, zero `taxonomy_nodes_ext` rows) `cortexOntologyVersion()` must return
**`onto1:76d1f3ad728b382b`**. Any ext node, any admin-confirmed verb, or any label
edit legitimately moves it — always grade on a fresh store.

Note that no *lifted* test asserts that literal string; `onto1-agreement.test.ts`
proves runtime ≡ reference only *relatively*. Pinning the literal is build-step 5's
job and is still outstanding.

## Not done yet

- **Step 4 — store.** `server/db.ts:29-30` captures `KEAP_DATA_DIR` at module load
  and hardcodes the filename `keap.db`. Pointing the organ at `~/cortex/data/cortex.db`
  needs an explicit decision: accept `~/cortex/data/keap.db` (env var alone, zero
  source edits) or edit that one line and give up strict byte-identity on `db.ts`.
- **Step 5** — pin the literal digest in a test.
- **Steps 6–8** — ANN index, `server/index.ts` daemon, e2e. `package.json`'s `build`
  and `start` scripts already name `server/index.ts` / `dist-server/index.js`; that
  entrypoint does not exist yet, so `npm run build` does not run.
- **Steps 9–13** — Ansible role, plugin, CI jobs, blank verify, KEAP cutover.

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
