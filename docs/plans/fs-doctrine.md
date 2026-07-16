# nOS Filesystem Doctrine — unified, structured, isolated storage

> **Status: DESIGN (P0) — review before any implementation.** No live data moves
> until this is approved. Motivated 2026-07-16: ad-hoc per-service volume paths
> block safe multi-tenant / multi-user / multi-agent-per-user isolation, and gate
> the calibre-web→Autocaliweb fix (REM-074) + the Puter→euro-office→KEAP document
> flow. Design-first (memory `agents-drive-operator-supervises`).

## 1. Problem — the current layout is scattered and flat

- **42 independent `*_data_dir` / `*_config_dir` vars**, each defaulting to a bare
  `~/<service>` (e.g. `nextcloud_data_dir: ~/nextcloud-data`,
  `mariadb_data_dir: ~/mariadb/data`, `calibreweb_books_dir`, `keap_data_dir`).
- **`tasks/stacks/external-paths.yml`** re-points them to an external SSD via ~47
  per-path `set_fact` overrides — the only unifying mechanism, and it is a flat
  list, not a tree.
- **Zero tenant / user / agent isolation** in the layout. Everything a service
  writes lands in one flat dir; there is no filesystem boundary between users, and
  no per-agent scratch scoping. A future multi-tenant host cannot isolate tenant A's
  documents from tenant B's at the filesystem level.
- `~/.nos/` is the **runtime sidecar** (regenerable state, logs, events) — distinct
  from persistent data; it stays as-is.

This blocks three things the platform needs: (a) **multi-tenant/user/agent security
isolation**, (b) the **calibre-web→Autocaliweb** fix (needs a library volume remap —
must be doctrine-conformant, not ad-hoc), (c) the **Puter→euro-office→KEAP** document
flow (documents must live somewhere structured that the KEAP consolidator auto-maps).

## 2. Target tree

Single root `nos_data_root` (one knob, override to external SSD). `~/.nos/` unchanged.

```
{nos_data_root}/                         # default {{ HOME }}/nos ; external SSD via ONE override
├── platform/                            # platform-owned; not tenant/user data      (0700 operator)
│   └── services/<svc>/                  # engine data: DBs, indexes, service config
│       ├── mariadb/ postgresql/ redis/  #   infra engines
│       ├── authentik/ infisical/ traefik/
│       ├── grafana/ prometheus/ loki/ tempo/ influxdb/
│       ├── gitea/ gitlab/ woodpecker/ portainer/ rustfs/
│       └── keap/                        #   KEAP's libSQL/keap.db (engine, not user docs)
├── tenants/<tenant>/                    # per-tenant isolation                       (0710 tenant-grp)
│   ├── shared/<svc>/                    # tenant-wide, APP-managed multi-user content
│   │   ├── nextcloud/ library/ media/ zim/ maps/   # calibre library, jellyfin media, kiwix…
│   │   └── wordpress/ bookstack/ outline/ …
│   └── users/<uid>/                     # per-user isolation, key = X-Authentik-uid  (0700 owner)
│       ├── documents/                   # ← Puter & euro-office WRITE here
│       ├── inbox/                       # ← per-user KEAP consolidator drop dir
│       └── agents/<agent>/              # per-agent-per-user scratch/state           (0700)
└── shared/                              # cross-tenant explicit shared (rare)        (0710)
```

## 3. The load-bearing insight — three data classes isolate differently

Not everything can (or should) be filesystem-isolated per user. Classify every store:

| Class | What | Where | Isolation mechanism |
|---|---|---|---|
| **1 — Platform engine** | DBs, caches, indexes, service internals (mariadb, postgres, redis, authentik, grafana, gitea, keap.db, …). Single-purpose infra or app that manages multi-user *internally*. | `platform/services/<svc>/` | Not user-scoped; 0700 operator. Unified + structured, not FS-isolated per user. |
| **2 — Tenant-shared content** | App-managed multi-user content stores (Nextcloud data, calibre **library**, Jellyfin media, Kiwix ZIMs, WordPress). The **app** enforces per-user access. | `tenants/<t>/shared/<svc>/` | One dir per tenant; the app does multi-user. nOS gives the mount, app owns ACLs. |
| **3 — FS-native per-user** | Filesystem-native per-user data: **Puter files, euro-office documents, calibre library (operator decision 2026-07-16: personal), KEAP inbox, agent scratch**. No app-internal multi-user — the filesystem *is* the boundary. | `tenants/<t>/users/<uid>/…` | **Real nOS-level isolation**: 0700 owner dirs + per-user mount scoping. This is where isolation actually bites. |

> **Decisions locked 2026-07-16:** (1) `nos_data_root` = **absolute path, default `~/nos`,
> works out-of-the-box** (external SSD is just a different absolute value, not special-cased).
> (2) short `nos_tenant_slug` (e.g. `pazny`), full domain kept separately. (3) **calibre library
> is PER-USER (class 3)**, not tenant-shared — sharing is a separate roadmap item (see §9).
> (4) macOS cannot give real per-user POSIX isolation (single UID) → on macOS multi-tenant =
> **multiple instances / more HW**; the **playbook must be Linux-"real-server"-ready** where
> distinct UIDs make per-user 0700 isolation genuine. **Single-user reality:** the system has one
> user today, so **breaking changes are acceptable without an in-place migration** — the test is a
> `--blank --full` run, so P1 is clean role defaults, NOT a migration recipe (see §7-8).

**Consequence:** the user's "isolate" goal is fully achievable for **class 3** (and
that is exactly the euro-office/Puter/KEAP/agent flow). Classes 1–2 get "unify +
structure" (one root, consistent tree, one external-SSD knob) but continue to rely on
app-internal multi-user — which is correct, not a compromise: re-implementing
Nextcloud's per-user store at the FS level would be wrong.

## 4. What this unblocks (the three motivating threads)

- **calibre-web → Autocaliweb (REM-074).** The calibre **library** is class-2 shared
  content → `tenants/<t>/shared/library/`. Autocaliweb's `/calibre-library` mount then
  points at the doctrine path — a **conformant** remap, decided by the doctrine, not an
  ad-hoc per-migration volume change. The fork migration becomes a clean role edit.
- **Puter → euro-office → KEAP.** Documents are class-3 → `tenants/<t>/users/<uid>/
  documents/`. Puter (`os.<tld>`) mounts the user's `documents/`; euro-office edits the
  same files (redirect from Puter); the **KEAP consolidator** walks
  `tenants/*/users/*/documents` + `.../inbox` and auto-maps every user's documents into
  the cortex, per-user scoped. (The consolidator already reads `NOS_CONSOLIDATE_FS_ROOTS`
  — this just makes those roots the structured tree instead of scattered paths.)
- **Multi-tenant/user/agent isolation.** 0700 user dirs + per-user mount scoping mean a
  container/agent acting for user A cannot read user B's `documents/`; agents get a
  scoped `agents/<agent>/` under the user they act for.

## 5. Resolver + collapse of external-paths.yml

- New var `nos_data_root` (default `{{ HOME }}/nos`). Every path is defined ONCE in
  `default.config.yml` (the single global source) as
  `<svc>_data_dir: "{{ nos_data_root }}/platform/services/<svc>/<leaf>"` (class 1) or
  `{{ nos_data_root }}/tenants/{{ nos_tenant_slug }}/shared/<svc>/<leaf>` (class 2);
  class-3 paths resolve per-uid at request/provision time (P2).
- **Why config-single-source, not role defaults** (learned in P1, 2026-07-16): these vars
  are referenced *before the owning role runs* — core-up dir-creation (`core-up.yml`),
  `blank-reset`, and the **plugin/wiring loader** (invoked `template_vars: {{ vars }}`).
  A role-default-only value is undefined in that eager-resolve namespace and aborts the run
  (`| default()` does NOT save it, and some `plugin.yml` path refs have no default at all).
  So paths live in `default.config.yml` (global) and NOT in role defaults — which is also
  fewer total lines than the old scattered config-shadow-role pattern (net −22 in P1).
- **`external-paths.yml` collapses to ONE knob**: set `nos_data_root` to
  `/Volumes/SSDxTB/nos` and the entire tree relocates — replacing 47 per-path overrides.
  (Keep a thin compat shim for any path that must diverge.)
- `tenant_slug` derives from `tenant_domain` (single-tenant today = one entry; the tree
  is multi-tenant-ready from day one, no schema rework later — mirrors the KEAP
  sharing-ready data-model decision).

## 6. Isolation / permission model

| Dir | Mode | Owner/grp | Rationale |
|---|---|---|---|
| `platform/` | 0700 | operator | engine data, operator-only |
| `tenants/<t>/` | 0710 | operator : `nos-t-<t>` | tenant group can traverse, not list-all |
| `tenants/<t>/shared/` | 0770 | operator : `nos-t-<t>` | tenant-wide app content |
| `tenants/<t>/users/<uid>/` | 0700 | `<uid-mapped>` | **per-user boundary** |
| `…/users/<uid>/agents/<agent>/` | 0700 | `<uid-mapped>` | agent scratch, scoped to the user it serves |

Containers: class-3 services mount **only** the relevant user subtree (per-user
instance or request-scoped bind); class-1/2 mount their single dir. Enforcement =
mount scoping + POSIX perms; Docker-Desktop-on-macOS UID mapping quirks noted as a
Phase-3 risk (VirtioFS / PUID:PGID alignment).

## 7. No migration recipe — single-user, breaking-OK

Because the system has exactly one user today (operator decision 2026-07-16), there is
**no in-place data migration** — a `--blank --full` run rebuilds everything under the new
tree. This deletes the P4 "migrate 42 live dirs" work entirely and keeps the roles clean:
each role's default simply *points at the new path*, and the next blank creates it there.
(If a multi-tenant "real server" later needs in-place moves without a blank, author a
proper `files/anatomy/migrations/<date>-fs-doctrine.yml` then — not now.)

## 8. Phasing (revised — no migration)

- **P0 — Design (this doc) + review.** ← we are here. No data moves.
- **P1 — Resolver + native layout.** Introduce `nos_data_root` (+ `nos_tenant_slug`);
  reclassify all 42 `*_data_dir`/`*_config_dir` defaults under the tree by class. Collapse
  `external-paths.yml` to the single `nos_data_root` knob. Gate `test_fs_doctrine_paths.py`
  (every path resolves under `nos_data_root`, correct class). **Clean role defaults, no
  bloat** — validated by the operator's `--blank --full`.
- **P2 — Per-user tree + class-3.** `tenants/<t>/users/<uid>/{documents,library,inbox,
  agents}`; rewire KEAP consolidator roots + Puter user-file mounts + calibre-web→
  Autocaliweb (library now a class-3 per-user doctrine path). Unblocks euro-office/KEAP.
- **P3 — Isolation + agent enforcement.** POSIX perms (Linux real UIDs) + per-user mount
  scoping; **AgentKit tool-layer FS scoping** — `BashReadOnlyTool` + a new FS-write tool
  must reject any path outside the agent's authorized `tenants/<t>/users/<uid>` scope
  (agents already have NO arbitrary bash — execve-argv-allowlisted read-only — the gap is
  path-scope). RBAC→FS: the agent session carries its tenant/user scope; the tool checks
  the resolved realpath against it. **KEAP DataTables RBAC is the proven precedent**
  (owner+visibility+tier, live-verified 2026-07-16: cross-user read/write both 404).

## 9. Related threads (spun to roadmap)

All four original open questions are **decided** (see the boxed note in §3). Adjacent work
this epic surfaced:

- **Calibre / content sharing** (calibre is per-user; sharing deferred). The robust,
  low-duplication shape: **KEAP owns the sharing relationship as a DB row** (visibility +
  owner — the DataTables/content model is already sharing-ready and RBAC-enforced,
  live-verified), files live once in a shared content store, per-user "library" is a
  DB-filtered view — *not* file duplication. A symlink-per-share works but is more fragile
  (broken links across container mount boundaries). Prefer DB-row visibility over symlinks.
  → roadmap.
- **`config.yml`/`default.config.yml` bloat** — the config surface is outgrowing itself
  (42 path vars among ~87 toggles + hundreds of tuning vars). A separate config-revision
  pass (group/namespace/derive) is due; P1 should *reduce* path-var lines where a derivation
  removes them, not add. → roadmap.
- **AgentKit SW gating** (the §8-P3 enforcement, worth its own design) — agents call tools
  not bash (already true: `BashReadOnlyTool` is execve-argv-allowlisted read-only); the gap
  is (a) FS path-scoping so a tool refuses a "foreign" (non-authorized) subtree, (b) a
  future FS-write tool that is scope-checked from birth, (c) RBAC→FS mapping in the DB. → roadmap.
```
