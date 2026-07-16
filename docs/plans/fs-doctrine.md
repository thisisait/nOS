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
| **3 — FS-native per-user** | Filesystem-native per-user data: **Puter files, euro-office documents, KEAP inbox, agent scratch**. No app-internal multi-user — the filesystem *is* the boundary. | `tenants/<t>/users/<uid>/…` | **Real nOS-level isolation**: 0700 owner dirs + per-user mount scoping. This is where isolation actually bites. |

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

- New var `nos_data_root` (default `{{ HOME }}/nos`). Every class-1 default becomes
  `<svc>_data_dir: "{{ nos_data_root }}/platform/services/<svc>"`; class-2 →
  `{{ nos_data_root }}/tenants/{{ tenant_slug }}/shared/<svc>"`; class-3 paths resolve
  per-uid at request/provision time.
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

## 7. Migration — a proper nOS migration, never ad-hoc

Moving 42 live dirs into the tree is a **data migration**, authored as
`files/anatomy/migrations/<date>-fs-doctrine.yml` with `detect`/`action`/`verify`/
`rollback` per step, converge-driven, idempotent, **opt-in** (`-e migrate_fs_doctrine=
true`; breaking-migration confirm gate). Never `mv` volumes by hand. New/blank installs
get the tree natively; existing installs migrate explicitly under supervision.

## 8. Phasing

- **P0 — Design (this doc) + review.** ← we are here. No data moves.
- **P1 — Resolver + native layout.** Introduce `nos_data_root`; reclassify all 42
  defaults under the tree (class 1/2). Blank installs get the structured tree.
  external-paths.yml → single `nos_data_root` knob. Gate: `test_fs_doctrine_paths.py`
  (every `*_data_dir` resolves under `nos_data_root`, correct class).
- **P2 — Per-user tree + class-3.** `tenants/<t>/users/<uid>/{documents,inbox,agents}`;
  rewire the KEAP consolidator roots + Puter user-file mounts. Unblocks euro-office/KEAP.
- **P3 — Isolation hardening.** perms model + per-user mount scoping + macOS UID-mapping.
- **P4 — Migration recipe** for existing installs (§7); calibre-web→Autocaliweb lands here
  (its library is already at the class-2 doctrine path by P1).

## 9. Open questions for the operator

1. Root default: `{{ HOME }}/nos` vs XDG `{{ HOME }}/.local/share/nos` vs external-first?
2. `tenant_slug` derivation (full domain vs a short slug) — affects on-disk path length.
3. Class-2 boundary calls: is the **calibre library** tenant-shared or per-user? (Books
   feel shared; personal reading progress is per-user and already lives in KEAP.)
4. macOS single-UID reality: real per-user POSIX ownership needs distinct UIDs; on a
   single-operator Mac all containers run as one user. Is per-user isolation a **Linux/
   multi-tenant-host** guarantee, with macOS single-operator getting structure-only?
```
