# P-3: the nOS cortex organ — design + build plan

## 1. Decision

The cortex reasoning backend moves into the nOS anatomy as **`pazny.cortex` — a first-class Node host organ**, the fourth brain beside Bone (signals), Wing (observes), and Pulse (keeps time): **Cortex remembers and reasons.** It is a standalone loopback daemon on `127.0.0.1:8098` (launchd `eu.thisisait.nos.cortex` on macOS / `systemd --user nos-cortex` on Linux), built from a **verbatim TS/Node port** of KEAP v1.27.0's `cortex-*` modules vendored under `files/anatomy/cortex/`, owning a **single libsql store** whose reasoning tables port byte-for-byte from KEAP's schema and whose ANN index is tuned to the measured optimum (float8 + `max_neighbors=20`). It exposes `POST /agent/v1/validate`, `GET /agent/v1/validate/opcodes`, a new `/agent/v1/context` recall endpoint, and a drift-stamped `/health`, gated by KEAP's scope-split bearer tokens (grafted onto Bone's Authentik-JWKS middleware for one audited auth surface). KEAP sheds its reasoning backend (P-5) and re-points its cortex client at this organ, keeping only UI + product backend. Because the daemon is a native host process reading a host-local store, it **dissolves the Wing-executor §8 network risk** (launchd→launchd loopback, no Wing-host→container hop) and **colocates the recall gate + embed-sync with the host Ollama embedder** where they are architecturally forced to live.

## 2. Where it sits — anatomy integration

| Surface | Concrete path / value | Scaffold from |
|---|---|---|
| **Source tree** | `files/anatomy/cortex/` (vendored Node/TS package) | `files/anatomy/face` (vendored Node precedent), `files/anatomy/bone` (host-organ precedent) |
| **Role** | `roles/pazny.cortex/{defaults,tasks,templates,handlers,meta}/main.yml` | `roles/pazny.bone/` 1:1 |
| **main.yml hook** | `import_role: name=pazny.cortex` in the host block, **right after `pazny.bone`, before Wing/Pulse** so its loopback is up when they start | Bone import site |
| **launchd (macOS)** | `templates/cortex.plist.j2`, label `eu.thisisait.nos.cortex`, `RunAtLoad`+`KeepAlive`, `ThrottleInterval 30`, `Soft/HardResourceLimits NumberOfFiles 8192` (libsql WAL holds db + `-wal` + `-shm`) | `bone.plist.j2` verbatim |
| **systemd (Linux)** | `include_role: pazny.linux.systemd_user tasks_from=ensure_unit` — `su_name=nos-cortex`, `su_exec_start=node dist-server/index.js`, gated `nos_service_manager=='systemd-user'` | Bone Linux pilot |
| **Port** | `cortex_port: 8098` (new var; beside Bone's 8099), loopback-only | Bone `bone_port` |
| **Secrets** | `cortex_ro_token` / `cortex_rw_token` (`{{ global_password_prefix }}_pw_cortex_*` in `default.credentials.yml`); `cortex_ollama_url` (default `http://127.0.0.1:11434`, MLX); optional `AUTHENTIK_OIDC_ISSUER`/JWKS reused from Bone | KEAP `server/tokens.ts` scope-split |
| **Plugin** | `files/anatomy/plugins/cortex-base/plugin.yml` — `authentik:` ro-token, `notification:` fanout, `pulse_jobs:` (`keap-embed-sync`), `observability:`, `requires: [ollama]`, GDPR row. KEAP's `keap-base` gains `cortex_backend_url` env | `bone-base`, `hermes-base` |
| **state/manifest.yml** | row `cortex` with `domain_var: cortex_domain`, `port_var: cortex_port` — Traefik file-provider routes it via `host.docker.internal:8098` **only on explicit opt-in**; default no route | Bone manifest row |
| **Store dir** | `~/cortex/data/` (outside the playbook tree, like `~/.nos`; `git clean` cannot wipe reasoning history; native host file sidesteps the backrest VirtioFS blocker) | `bone_state_dir` doctrine |

KEAP's `cortex-base` Docker plugin stays but sheds the reasoning backend; **`cortex-base` is the new host-organ plugin** owning the `/agent/v1` token surface and the optional public route.

## 3. Runtime store + ANN

- **Engine:** single **libsql `cortex.db` (WAL)**, sole-writer = this organ, at **`~/cortex/data/cortex.db`** (config var `cortex_store_path`). Schema is the verbatim port of `server/db.ts` `SCHEMA[]` (`concept_relations`, `node_features`, `node_metadata`, `taxonomy_nodes_ext`, `node_descriptions`, `knowledge_imports`, `curator_runs`/`visits`) + `server/migrations.ts` (`relations`, `relation_types` — the `seed|confirmed|proposed` verb vocabulary the resolver reads) + `VECTOR_SCHEMA` `embeddings(kind, ref_id, model, dim, content_hash, vector F32_BLOB(768))` + `libsql_vector_idx(vector)` + fts5 `taxonomy_fts` + `corpus_fts`.
- **ANN tuning (MEASURED optimum):** build `libsql_vector_idx` at **float8 + `max_neighbors=20`** → **65.6 MB / 1.72 ms/query, recall@10 = 100%**. **NOT float1bit** (degrades first as N grows). The `CREATE INDEX` param is fixed in the schema/build step. **Retune at 20–50k nodes** via `scripts/ann-recall.mjs --vectors <exported.json>` (exhaustive `vector_distance_cos` ground truth vs each variant's overlap).
- **Durable vs regenerable:** the ~4.2 MB reasoning + shared block is the durable seed; the ANN + FTS indexes are **regenerable** and rebuilt on first boot / after each embed-sync. Wrap index creation in the `vectorsOk` try/catch so a stock-SQLite build degrades to FTS-only rather than crashing.
- **`databaseId` drift stamp:** `getDbIdentity()`/`establishDbIdentity()` UUID in `app_settings key='db_identity'`; `''` before `initDb` fails **CLOSED**. On cutover the organ's store MUST carry over KEAP's existing `db_identity` UUID (see Open Questions) or Wing's dispatch rule rejects every pre-cutover binding.
- **Recall gate + embedder wiring:** the embedder is **deliberately out of the organ** — `scripts/recall-gate.mjs` and `ann-recall.mjs` move to `files/anatomy/cortex/scripts/` and reach **host Ollama** (`nomic-embed-text`) via `cortex_ollama_url`. The `pending → /api/embed → POST-back` embed loop runs as a **Pulse job `keap-embed-sync`** declared in `cortex-base` `pulse_jobs:`. `recall-gate.mjs` exit codes stay **0 pass / 1 fail / 4 SKIP** (4 = no embedder reachable, **never** a pass). The recall gate and the embedder are colocated on the host by design.

## 4. Port plan (P-4)

**Source of truth:** `~/projects/knowledge-explorer-and-preserver` on branch **`dev` @ v1.27.0 (HEAD `0e4a87d`)** — it subsumes the entire `feat/cortex-validate` line (lexer/parser `f48c94c`, resolver+route `eb08059`, FTS/candidate fixes `6171be6`, P-1 spine-as-data `da4d102`, P-2 onto1 contract `b931822`). **`~/keap/src` is v1.26.0 with ZERO cortex code — never port from it.** This is the exact ref `roles/pazny.keap` already pins (`keap_repo_ref: v1.27.0`), so cortex source and deployed KEAP image share one git tag today — the coupling is pre-established.

**Port discipline (PORT, not rewrite — a rewrite breaks byte-identical onto1 and both sides silently reject each other's ASTs):**

| Module | Lift |
|---|---|
| `server/cortex-lang.ts` (tokenizer/LL(1) parser/AST/structural) | **VERBATIM** — imports only `./cortex-opcodes`, zero DB/IO |
| `server/cortex-opcodes.ts` (frozen `as const` registry, 14 opcodes, `cx1:` hash) | **VERBATIM** |
| `shared/contracts/cortex.ts` (the only zod envelope) | **VERBATIM** |
| `server/cortex-resolve.ts`, `cortex-ontology-version.ts`, `cortex-validate.ts` | **import-path rewrites only** — all reads are SELECT/in-memory (read-only) |
| DB/tree deps (`server/db.ts`, `migrations.ts`, `taxonomy.ts`, `src/game/data/taxonomy.ts` subsets) | copy the touched subset |
| `knowledge/{onto1-compose.mjs, onto1-conformance.mjs, spine/, fixtures/onto1/}` + `docs/specs/*` + tests | copy |

**The four onto1 traps as explicit test guards** (the port MUST reproduce **`onto1:76d1f3ad728b382b`** over 790 nodes or it silently rejects KEAP's ASTs):

- **§2.2 fixpoint** — 12-pass ext registration (`MAX_REGISTRATION_PASSES=12`); pinned by fixture **`case-02-fixpoint`**.
- **§2.3 existing-id-wins-AND-consumes-the-row** — pinned by **`case-04-collision`**.
- **§3.1 sort by UTF-16 code units, NOT `localeCompare`** (`byCodeUnit`) — pinned by **`case-06-unicode-and-tabs`**.
- **§3.3 `description` deliberately EXCLUDED** from the vocabulary — asserted in `onto1-agreement.test.ts` + the canonical serialization.

**Test suite (~215) lifts as-is:** vitest `server/**/*.test.ts` + `knowledge/**/*.test.mjs` = `cortex-lang.test.ts` (83) + `cortex-resolve.test.ts` (54) + `onto1-agreement.test.ts` (4, the non-circular equivalence proof: runtime tree vs git-spine-as-data) + the rest; `e2e/validate.spec.ts` (12 Playwright, against built `dist-server/index.js`) via `npm run test:e2e`.

**CI gate:** add a Node **`cortex`** job to `.github/workflows/ci.yml` modeled 1:1 on the existing `face` job (`actions/setup-node@v4` node-version **22**, npm cache, `npm ci` → `npm run build` → `npm test` → `npm run test:e2e`). Add `node knowledge/onto1-conformance.mjs` as a **shared conformance gate that BOTH the nOS cortex organ and the retained KEAP repo must pass on every push**. Wrap the suite in a `tests/anatomy/` pytest shim, mirroring the composer lockfile-sync discipline (validate `package-lock.json` on every push). **Grading = KEAP v1.27.0 conformance:** the 6 fixtures + digest are the pass/fail line.

**Runtime + build:** Node 22, npm + committed `package-lock.json` (NOT pnpm — keep the toolchain uniform with `face`). Deps as KEAP ships: `libsql ^0.5.29`, `zod ^3.23.8`, `express ^4.21.0`; dev `tsx ^4.19`, `typescript ^5.5`, `vitest ^4.1.9`, `@playwright/test`; `type: module`, ESM throughout. **libsql is a native napi module** — `npm ci` must fetch the arm64-macOS AND linux-x64 prebuilds at role build time. Build shape mirrors `face`: rsync vendored source into a build dir (exclude `node_modules`) → `npm ci` → `npm run build` (→ `dist-server/index.js`, the same target KEAP's e2e uses) → the daemon runs the **built bundle**, `tsx` stays dev-only.

## 5. Security / token surface

- **Callers (3 classes):** (1) **Wing executor** — validates ASTs before dispatch, re-validates on binding drift; host loopback, no bearer needed under the in-Wing identity. (2) **Host AgentKit** (`run-agent.php`, claude-CLI runners) — author cortex programs, call validate/context in the same trust zone. (3) **Pulse** — the only true cross-process caller: `keap-embed-sync` (vector upserts, **RW**) + `recall-gate.mjs` (read). Pulse never calls validate.
- **Token model (port `server/tokens.ts` verbatim):** **RO** = read the corpus (validate is `agentAuth('ro')` — zero side effects); **RW** = read + allowlisted writes (embed-sync upserts); **CAPTURE** stays with KEAP (device intake, not a cortex concern). Compare with **`crypto.timingSafeEqual`** over sha256 (`tokenEquals`) — never `===`. Graft: route the `/agent` auth through **Bone's already-vetted loopback token + Authentik-JWKS middleware** and emit a **Bone audit event for every validate/recall call** (audit lineage + single auth surface, without Python Bone proxying the TypeScript core).
- **Loopback-identity refusal (fail-closed, KEAP `KEAP_TRUSTED_PROXY` analogue):** the organ has no human `/api` surface, so the `X-Authentik-*` header path is N/A — but the same invariant holds: a tokenless/identityless request → **401/503, never an implicit identity**. Adopt KEAP's opt-in pattern — when no token is configured, `agentAuth` answers **503 "agent surface disabled"** (`!TOKEN_RO && !TOKEN_RW ⇒ 503`), so the surface is never open by accident.
- **Corpus privacy:** the organ's **operational** tables (validate cache, `ast.binding` stamps, drift log, agent sessions) are NEVER registered as an embeddable `embeddings.kind` (allowlist `taxonomy|capture|note|object`) and NEVER appear in `hybridSearch`/recall — preserve KEAP's `kind`-filtered fts5 split (`taxonomy_fts` vs `corpus_fts`).
- **Pure loopback default:** NO default Traefik route (Bone/Wing/host AgentKit/Pulse are the only callers, unreachable from containers per the A19-verified scope-split); a public `/agent` route is explicit opt-in only — shrinking the surface below the base proposal.
- **wing-executor §8 — what dissolves vs remains:** **#6 (Wing-host → KEAP-container network path) FULLY DISSOLVES** — validate/context is now in-process or host-loopback in one trust zone, so there is no host→container hop, no `KEAP_AGENT_URL` reachability question, no `gated_net` traversal, no header-forge surface. Cross-**tenant** isolation is unchanged (the agent bearer is system-scope; `svc:` tenant-scoped via `hub_systems`, `db:`/`doc:` host-global) — that gap remains and is orthogonal to placement.

## 6. Build sequence

1. **Scaffold the empty organ** — `git subtree`/copy the port set into `files/anatomy/cortex/` (the verbatim modules + DB/tree subset + `knowledge/` + `docs/specs/` + tests); add `package.json` (`type: module`, pinned deps) and `tsconfig.json`.
2. **Freeze the toolchain** — `npm install` → commit `package-lock.json`; verify `npm run build` emits `dist-server/index.js` and the arm64-macOS + linux prebuilds of `libsql` resolve.
3. **Green the pure port first** — `npm test` passing `cortex-lang.test.ts` (83) + opcode/registry-hash cases with **zero DB** — proves the verbatim modules lifted cleanly.
4. **Wire the store** — point `cortex-resolve.ts`/`cortex-ontology-version.ts` at `~/cortex/data/cortex.db`; run `initDb` + migrations; green `cortex-resolve.test.ts` (54) against a seeded libsql.
5. **Pin onto1 byte-identity** — `node knowledge/onto1-conformance.mjs` passes all 6 fixtures (§2.2/§2.3/§3.1/§3.3) AND `onto1-agreement.test.ts` (4) reproduces **`onto1:76d1f3ad728b382b`** over 790 nodes. **This is the hard gate — do not proceed until green.**
6. **Build the ANN index** — `CREATE INDEX libsql_vector_idx` at float8 + `max_neighbors=20`; confirm `ann-recall.mjs` reports recall@10 = 100% / ~1.72 ms/q on the current corpus; verify `vectorsOk` degrades cleanly on a no-vector build.
7. **Stand up the daemon** — bind `127.0.0.1:8098`; mount `POST /agent/v1/validate` + `GET /validate/opcodes` + new `/agent/v1/context` + drift-stamped `/health`; wire the 503-when-tokenless fail-closed gate + timingSafeEqual bearer + Bone audit emit.
8. **e2e green** — `npm run test:e2e` (12 Playwright vs the built bundle): route mounted + RO-auth, typed-error-in-200 vs 400, deferred contract survives bundle, `ast.binding` agrees with `/health` + `/validate/opcodes`.
9. **Ansible-ize** — `roles/pazny.cortex` (defaults/tasks/templates/handlers/meta) cloned from `pazny.bone`: build step (rsync → `npm ci` → `npm run build`), `cortex.plist.j2` + `systemd_user ensure_unit`, `import_role` in `main.yml` after Bone; `cortex_port`/`cortex_store_path`/`cortex_ollama_url`/tokens in defaults + credentials; `state/manifest.yml` row.
10. **Plugin + Pulse + observability** — `files/anatomy/plugins/cortex-base/plugin.yml` (authentik ro-token, notification, `pulse_jobs: keap-embed-sync`, observability, `requires: ollama`, GDPR); confirm the embed-sync Pulse job reaches host Ollama and the recall gate exits 0.
11. **CI gate** — add the `cortex` Node-22 job to `.github/workflows/ci.yml` (build + `npm test` + e2e + `onto1-conformance.mjs`); wrap in a `tests/anatomy/` pytest shim; add the shared conformance gate to the retained KEAP repo's CI.
12. **Blank + live verify** — one clean `nos --remove=data --confirm`; assert the organ boots, `/health` carries agreeing `ontologyVersion`+`databaseId`+`opcodeRegistryHash`, Wing executor validates in-process, 61-container health stays clean.
13. **KEAP P-5 (separate PR, supervised)** — delete KEAP's `server/cortex-*.ts`, flip its client to `cortex_backend_url = http://host.docker.internal:8098`, and refactor KEAP to read reasoning **through the cortex API** (never a second writer on the libsql file). Carry over the `db_identity` UUID at cutover.

## 7. Open questions for the operator

1. **Two-writer cutover.** Today KEAP's `server/db.ts` reads the reasoning tables via direct SQL. Under single-writer cortex, does KEAP read reasoning **through the cortex API** (the correct end state, a real P-5 refactor), or do we accept a transitional **read-only shared `keap.db`** where cortex validates against the file KEAP still writes? The latter is faster to ship but is two-writers-on-one-libsql = corruption risk if KEAP ever writes reasoning rows.
2. **`db_identity` carry-over.** At cutover the cortex store MUST inherit KEAP's existing `db_identity` UUID, or every pre-cutover `ast.binding` fails the `databaseId` drift check and Wing **REJECTS** (not just revalidates). Confirm the migration copies `app_settings key='db_identity'`.
3. **First Node host organ cost.** Bone/Pulse are Python, Wing is PHP — adding nvm-Node + tsc + `@playwright/test` to host provisioning and CI is a new, heavy surface. Accept it, or trim (e.g. gate Playwright e2e behind the CI job only, keep it off host provisioning)?
4. **Two living onto1 implementations, forever.** The cortex organ and the retained KEAP repo must keep `onto1:76d1f3ad728b382b` byte-identical across two codebases. Is the shared `onto1-conformance.mjs` CI gate on both repos sufficient guardrail, or do we want a single vendored copy imported by both?
5. **Public `/agent` route.** Default is pure loopback (no Traefik). Do any external agents (outside Bone/Wing/Pulse/host AgentKit) ever need cortex, i.e. should we provision the opt-in `host.docker.internal:8098` file-provider route now, or leave it unbuilt until a caller appears?
6. **Store location vs backup.** `~/cortex/data/cortex.db` sidesteps the backrest VirtioFS blocker (host daemon backs up its own local file). Confirm the backup role includes `~/cortex/data/` in the host-daemon restic set, and decide whether the regenerable ANN/FTS indexes are excluded from backup (rebuilt on restore) to shrink the snapshot.