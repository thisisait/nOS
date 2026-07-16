# Filesystem Doctrine

> Canonical decisions. Detail + phasing: [`docs/plans/fs-doctrine.md`](../plans/fs-doctrine.md).

**One root.** All persistent data lives under a single absolute `nos_data_root`
(default `~/nos`, works out-of-the-box; point it at an SSD by setting one var). `~/.nos/`
stays the *runtime sidecar* (regenerable state/logs) — never persistent data.

**One knob for relocation.** `nos_data_root` is the only path override. `external-paths.yml`
sets that one var, not 47 per-service paths.

**Structured tree:**

```
{nos_data_root}/
├── platform/services/<svc>/            # class 1 — engine data (DBs, indexes, config)     0700
├── tenants/<nos_tenant_slug>/
│   ├── shared/<svc>/                    # class 2 — app-managed multi-user content         0770
│   └── users/<uid>/                     # class 3 — FS-native per-user (uid=X-Authentik-uid) 0700
│       ├── documents/  library/  inbox/  agents/<agent>/
└── shared/                             # cross-tenant, explicit, rare
```

**Three data classes — they isolate differently (the load-bearing rule):**

1. **Platform engine** — DBs/indexes/service state. App does multi-user *internally*.
   → `platform/services/<svc>/`. Unified + structured, not FS-isolated per user.
2. **Tenant-shared content** — app-managed shared stores (Nextcloud, media, ZIM, repos).
   The **app** owns per-user ACLs. → `tenants/<t>/shared/<svc>/`.
3. **FS-native per-user** — Puter files, euro-office docs, **calibre library (personal)**,
   KEAP inbox, agent scratch. The filesystem **is** the boundary. → `tenants/<t>/users/<uid>/`.

**Isolation is real only on Linux.** Per-user 0700 needs distinct UIDs. macOS runs every
container as one user → macOS gets *structure*, not per-user isolation; macOS multi-tenant =
separate instances/HW. **The playbook must stay Linux-"real-server"-ready** so class-3 0700
isolation is genuine there.

**Never bypass the tree.** No ad-hoc volume mounts outside `nos_data_root`. Migrations
(fork swaps, remaps) mount doctrine paths, never invent new ones. Agents may only touch a
subtree their scope authorizes — the tool layer enforces `realpath ∈ scope` (AgentKit gating).

**What is IN the tree vs intentionally OUTSIDE (P1 + P1b, 2026-07-16).** Every *service*
data/config path derives from `nos_data_root` — the 48 P1 vars (data/config/books) + the P1b
engine vars (onlyoffice db/lib/logs, loki/prometheus/tempo storage, jellyfin cache, spacetimedb
keys, pg certs, firefly up/export, code-server workspace). **Intentionally OUTSIDE the tree**
(host-owned or not-service-data — moving them would be wrong): host daemons (wing/bone/hermes/
openclaw app+runtime+state dirs), host binaries + tap installs (homebrew, opencode, ollama
models — also blank-persisted), the `~/.nos` runtime sidecar (+ node-exporter textfile under it),
the `~/stacks` compose root, TLS cert dir, and large user-provided media (`~/media`, blank-kept)
+ `~/projects/{nextcloud,wordpress}` source dirs. A stateful non-blank converge AFTER a path
move remounts to the new empty path and breaks the service — so on a live (non-blank) system,
finish path changes with a `--blank --full`, don't converge stateful services piecemeal.

**Single-user today → breaking-OK.** No in-place migration recipe; a `--blank --full` rebuilds
under the tree.

**Paths are GLOBAL, derived, single-source.** Every service path is defined once in
`default.config.yml` as `{{ nos_data_root }}/<class>/<svc>/<leaf>` — **not** in role defaults.
They must be global because they are referenced *before the owning role runs*: core-up
dir-creation, blank-reset, and the **plugin/wiring loader** (`template_vars: {{ vars }}`) all
read them, and a role-default-only value trips the eager-resolve trap (some plugin.yml refs
lack a `| default()`, so they hard-fail). Single-source (config-only, no role shadow) is also
what keeps the surface lean.
