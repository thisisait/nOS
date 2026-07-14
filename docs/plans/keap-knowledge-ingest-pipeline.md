# KEAP knowledge-ingest pipeline — git-SoT, role-driven, idempotent

**Status:** PLAN (2026-07-14). Greenlit **Full scope**. Replaces the manual
`docker exec node import-domain.mjs <key>` + hand-edited `Dockerfile` COPY
manifest (which bit us adding the fable physics bundles) with a git-sourced,
Ansible-driven, idempotent ingest that runs on every playbook run **and** on
`--blank`.

## Doctrine

- **Git is the single source of truth** for all core knowledge data (taxonomy
  blocks, descriptions, briefs, scaffolds, relation overlays). The live system
  is *populated from git*, idempotently, by the `pazny.keap` role — never by a
  hand-run `docker exec`. (`machinery-purpose-and-no-hacks`: complex systems
  install ONLY via the playbook.)
- **Idempotent + version-driven.** Each knowledge bundle carries a content hash;
  a `knowledge_imports` marker table records what was applied. Re-running skips
  unchanged bundles (no duplication, no volume spam); a changed bundle re-applies;
  a blank DB applies everything.
- **Two taxonomy views (user-toggle).** The knowledge graph a user sees is either:
  - **community** — the curated, git-tracked taxonomy (today: hardcoded / git-SoT;
    future: community-managed via a cloud push — "democratisation of positions").
    **This pipeline builds the community view.**
  - **custom** — the user's *local proposals* applied on top of community, for
    their own view. Local taxonomy edits are **proposals only**, pushable to the
    community cloud later. **OUT OF SCOPE now → roadmap** (see below).
- **Materialisation split.**
  - *Core taxonomy* (this pipeline — paragraphs/content at all levels) →
    git-driven ingest + **conditional container restart** (boot does
    registerExtNode → applyDescriptionOverride → rebuildFts → ensureLayout
    **append**; U1 layout of existing stars never re-bakes). Restart fires ONLY
    when the ingest actually applied a change.
  - *User data* → hot-reload (separate runtime path, not built here).

## Architecture

### 1. `knowledge/` = the git SoT tree (keap repo)
Move all core import data OUT of `deploy/` (which is baked into the image) into a
first-class `knowledge/` tree with per-domain subfolders. `deploy/` keeps only
runtime *code* (`seed-fixtures.mjs`, smoke scripts) + the ingest runner.

```
knowledge/
  _schema/            # JSON-schema(s) + shared house-style doc the linter enforces
  physics/            # phys-thermo … phys-biophys (8 fable bundles, rootIsSeed)
  math/               # math-blocks/-import/-scaffold
  chem/               # chem-*
  bio/                # bio-*
  toe/                # toe-blocks + toe-concept-graph
  ingest.mjs          # THE idempotent runner (generalises import-domain.mjs)
  lint.mjs            # bundle linter (schema + house-style gates)
```

### 2. `knowledge/ingest.mjs` — one idempotent runner
Generalises the per-domain `import-domain.mjs`:
- Scan `knowledge/**/*-import.json` (the applicable bundles).
- For each: compute `source_sha` (sha256 of the canonical bundle bytes). Compare
  to the `knowledge_imports` marker. **Skip if unchanged.**
- Apply changed bundles via the existing raw-SQL contract (rootIsSeed graft under
  seed L2, or grown-root catch-all; bilingual EN+CS; typed relation overlay).
- Upsert the marker; print a per-bundle line (`applied | skipped | dry`).
- `--dry-run`: report the plan (new / changed / unchanged + counts + would-restart)
  and exit 0 **without writing** — this is the CI gate.
- Exit non-zero only on a real error (unreadable/invalid bundle, DB failure).
- Emit a machine-readable summary (`{applied:[], skipped:[], changed:bool}`) the
  role reads to decide whether to restart.

### 3. `knowledge_imports` marker table (server/db.ts SCHEMA)
```sql
CREATE TABLE IF NOT EXISTS knowledge_imports (
  import_key TEXT PRIMARY KEY,
  source_sha TEXT NOT NULL,
  n_pillars  INTEGER NOT NULL DEFAULT 0,
  n_blocks   INTEGER NOT NULL DEFAULT 0,
  applied_at TEXT NOT NULL
);
```
Lives in the DB volume → survives restarts, resets on blank (fresh DB → all
bundles re-apply). The reconciliation is automatic; no separate backfill.

### 4. Delivery: bind-mount RO, NOT baked in the image
The role bind-mounts the git checkout's knowledge tree read-only:
`{{ keap_src_dir }}/knowledge:/knowledge:ro`. A RO bind-mount is **not** a docker
volume (no volume spam); it just decouples data from image rebuilds. **The fragile
`Dockerfile` per-bundle COPY manifest is deleted** — the image ships only code;
knowledge data rides the mount. Data changes need only a git ref advance + ingest,
never an image rebuild. (Image rebuild stays reserved for *code* changes.)

### 5. Dry-run + linter + CI (keap repo — bootstrapped fresh)
The keap repo has no CI yet; add a GitHub Actions workflow:
- `knowledge/lint.mjs` — validates every bundle: schema (root/pillars/blocks),
  desc 20–2000, `descriptionCs` present + **zero Cyrillic**, brief present,
  pillar-id index-alignment, slug uniqueness, parent-branch existence, `explored`
  enum. Exit non-zero on any violation.
- `ingest.mjs --dry-run` against an ephemeral scratch libSQL DB — catches runtime
  breakage without a live system.
- `npm run build` (existing) so type/build regressions are caught.
- Job runs on PR + push to the app repo.

### 6. `pazny.keap` role wiring (nOS)
After the container is healthy (existing health-wait):
1. Render the compose override with the `knowledge/` RO bind-mount.
2. `docker exec iiab-keap-1 node knowledge/ingest.mjs` (real apply; idempotent).
3. **If** the runner reports `changed:true` → `docker restart iiab-keap-1` +
   re-wait healthy (materialise). Else skip the restart.
4. Embed-sync so new descriptions get 768-dim vectors.
All gated on `install_keap`, tag-able, blank-safe (blank → fresh DB → full ingest
→ one restart). No `docker exec` outside the role ever again.

## Phases
- **P1 — app repo core:** create `knowledge/` tree, move the ~20 data files,
  write `ingest.mjs` (scan+hash+marker+dry-run) generalising `import-domain.mjs`,
  add `knowledge_imports` to SCHEMA, write `lint.mjs`. Keep `import-domain.mjs` as
  a thin shim (or delete once ingest covers it).
- **P2 — Dockerfile + CI:** strip the data COPYs (ship code only), add the GH
  Actions workflow (lint + dry-run on scratch DB + build).
- **P3 — role wiring:** compose RO bind-mount, ingest task + conditional restart +
  embed-sync in `pazny.keap`.
- **P4 — migrate + verify:** blank-safe + incremental proof; physics + math/chem/
  bio/toe all ingest from `knowledge/`; graph API verify (never host sqlite3);
  smoke green; `[layout] appended`, not `baked`.

## Roadmap (deferred, tracked here + docs/roadmap.md)
- **custom view — local proposal apply.** A user toggles to a personal view where
  their local taxonomy proposals are applied on top of community. Local edits are
  proposals (never mutate the community graph directly).
- **community cloud push.** Proposals push upstream to a community-managed cloud
  taxonomy — "democratisation of positions." Turns today's hardcoded community
  view into a community-governed one.
- **user-data hot-reload.** Non-taxonomy user data materialises live (no restart).

## Guardrails
- **NEVER host `sqlite3` on the live libSQL DB** — ingest runs in-container
  (libSQL driver); all inspection via `/agent/v1` / graph API. (2026-07-14
  corruption came from host sqlite3.)
- Idempotent + blank-safe: re-runs skip unchanged; blank re-applies all.
- Core-taxonomy restart is conditional (only on real change) + append-only (U1
  intact); user data is hot, not restart-driven.
