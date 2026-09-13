# Filesystem Doctrine

> Canonical decisions. Detail + phasing: [`docs/archive/fs-doctrine.md`](../../docs/archive/fs-doctrine.md).

## 1. One root

Persistent data SHALL live under a single absolute `nos_data_root` (default
`~/nos`; point it at an SSD by setting that one var). `~/.nos/` SHALL stay the
runtime sidecar (regenerable state/logs) — never persistent data.

## 2. One knob

`nos_data_root` SHALL be the only path override. `external-paths.yml` MUST set
that one var, not 47 per-service paths.

## 3. Tree

```
{nos_data_root}/
├── platform/services/<svc>/            # class 1 — engine data (DBs, indexes, config)     0700
├── tenants/<nos_tenant_slug>/
│   ├── shared/<svc>/                    # class 2 — app-managed multi-user content         0770
│   └── users/<uid>/                     # class 3 — FS-native per-user (uid=X-Authentik-uid) 0700
│       ├── documents/  library/  inbox/  agents/<agent>/
│       └── .face/state.db               # per-user structured KV (nOS-face user-state)
└── shared/                             # cross-tenant, explicit, rare
```

## 4. Three classes

They isolate differently — the load-bearing rule:

1. **Platform engine** — DBs/indexes/service state. App does multi-user
   *internally*. → `platform/services/<svc>/`. Unified + structured, not
   FS-isolated per user.
2. **Tenant-shared content** — app-managed shared stores (Nextcloud, media,
   ZIM, repos). The **app** owns per-user ACLs. → `tenants/<t>/shared/<svc>/`.
3. **FS-native per-user** — euro-office docs, **calibre library (personal)**,
   KEAP inbox, agent scratch, and **nOS-face user-state** (`.face/state.db` —
   personalization + app KV, outside the fs-sync classes so KEAP never ingests
   it). The filesystem **is** the boundary. → `tenants/<t>/users/<uid>/`.

A service SHALL be class-3 only if it stores REAL FILES. A web-desktop whose
"filesystem" is DB metadata + opaque UUID blobs is class-1 no matter how much
it looks like a file manager. The class-3 document producer feeding KEAP MUST
be a real-file service (Nextcloud). Puter established this (2026-07-18) and
was removed 2026-07-20; the rule outlived it
(`docs/archive/puter-and-document-flow.md`, `docs/archive/nos-face.md`).

## 5. Isolation

Per-user 0700 needs distinct UIDs. macOS runs every container as one user, so
macOS gets *structure*, not per-user isolation; macOS multi-tenant is separate
instances/HW. The playbook MUST stay Linux-"real-server"-ready so class-3 0700
isolation is genuine there.

## 6. Never bypass

A volume mount SHALL NOT sit outside `nos_data_root`. Migrations (fork swaps,
remaps) MUST mount doctrine paths, never invent new ones. Agents MAY only
touch a subtree their scope authorizes — the tool layer enforces
`realpath ∈ scope` (AgentKit gating).

## 7. In vs outside

Every *service* data/config path SHALL derive from `nos_data_root` — the 48 P1
vars (data/config/books) + the P1b engine vars (onlyoffice db/lib/logs,
loki/prometheus/tempo storage, jellyfin cache, spacetimedb keys, pg certs,
firefly up/export, code-server workspace). Intentionally OUTSIDE the tree
(host-owned or not-service-data — moving them would be wrong): host daemons
(wing/bone/hermes/openclaw app+runtime+state dirs), host binaries + tap
installs (homebrew, opencode, ollama models — also blank-persisted), the
`~/.nos` runtime sidecar (+ node-exporter textfile under it), the `~/stacks`
compose root, TLS cert dir, and large user-provided media (`~/media`,
blank-kept) + `~/projects/{nextcloud,wordpress}` source dirs.

A stateful non-blank converge AFTER a path move remounts to the new empty
path and breaks the service. On a live (non-blank) system, path changes MUST
finish with a `--blank --full`; they MUST NOT converge stateful services
piecemeal.

## 8. Breaking-OK

Single-user today. There SHALL be no in-place migration recipe; a
`--blank --full` rebuilds under the tree.

## 9. Paths

Every service path SHALL be defined once in `default.config.yml` as
`{{ nos_data_root }}/<class>/<svc>/<leaf>` — **not** in role defaults. They
MUST be global: core-up dir-creation, blank-reset, and the plugin/wiring
loader (`template_vars: {{ vars }}`) all read them *before the owning role
runs*, and a role-default-only value trips the eager-resolve trap (some
`plugin.yml` refs lack a `| default()`, so they hard-fail). Single-source
(config-only, no role shadow) is also what keeps the surface lean.
