# nOS face — the unified web-desktop shell

> Living design doc. Promoted from the approved plan 2026-07-18. Companion to the Puter
> investigation (`docs/plans/puter-and-document-flow.md`) that motivated it. The frontend
> lives in its own repo (`thisisait/nos-face`), deployed by `roles/pazny.face` (KEAP pattern).

## Context

Puter was meant to be the "nOS face" — the primary, cross-platform interaction surface on which
agents build real business apps for tenant companies (e.g. a hotel ordering system). The Puter
investigation found it is architecturally the wrong tenant: its VFS is **SQLite metadata + opaque
UUID blobs**, not real files, so it can't bridge to KEAP's real-file fs-sync, and its own
VFS/app/auth models conflict with nOS's. Meanwhile "manage & control & observe & audit" is
fragmented across Grafana, Authentik, Wing, KEAP, Nextcloud, Infisical.

**The reframe that de-risks this.** nOS already owns the *hard* parts of a webOS; only the
**shell** is missing:

| webOS capability | Status | Where |
|---|---|---|
| Identity w/o forced accounts | ✅ solved | Authentik forward-auth → `X-Authentik-*` → `ForwardAuthUserStorage` |
| App catalog / launcher | ✅ exists | `GET /api/v1/hub/systems` (public GET) + plugin `hub_card` |
| "Install an app" pipeline | ✅ exists | apps_runner: `apps/<name>.yml` → route + gate + registry + hub tile + GDPR |
| Agent-authors-a-file (safe) | ⚠️ half | AgentKit `MigrationWriteTool` (gated repo write → human merge → converge) |
| Real per-user filesystem | ✅ on disk | `tenants/<slug>/users/<uid>/{documents,library,inbox,agents}` (0700) |
| Windowing shell + file browser + liquid-glass | ❌ **the gap** | Puter was the wrong home for it |

So this is **a shell over an OS that already exists**, not a new OS — a bounded scope.

**Decisions:** (1) build fresh, composing existing nOS APIs (not a fork); (2) new repo
`thisisait/nos-face` + `roles/pazny.face` (git-cloned pinned ref, `face.<tld>`, Authentik-gated);
(3) walking skeleton first. Research verdict: no FOSS drop-in exists; only OS.js (BSD-2) fits a
fork but is low-momentum/bus-factor-1/vanilla-JS and would fight nOS's own VFS/app/auth. Liquid-
glass is cheap — an SVG `feTurbulence`→`feDisplacementMap` filter used as `backdrop-filter`.

## Architecture

```
                 face.<tld>  (Traefik + Authentik forward-auth — 0-login)
                      │  X-Authentik-{username,groups,email}  +  edge-token trust
        ┌─────────────┴──────────────────────────────────────────────┐
        │  nOS face  (SvelteKit + Vite SPA + thin node BFF)           │
        │  ── window manager: dock / windows / menubar                 │
        │  ── liquid-glass: SVG refraction filter + macos-web chrome   │
        │  App catalog ─────► GET /api/v1/hub/systems   (Wing, exists) │
        │  App windows  ────► iframe already-routed svc (Grafana/NC/…) │
        │  Install-app  ────► apps_runner manifest        (exists)     │
        │  Files (NEW)  ────► VFS API over users/<uid>/   (real files) │
        │  File-picker  ────► postMessage open/save dialog (2 modes)   │
        └──────────────────────────────────────────────────────────────┘
```

- **Identity / zero-login.** face sits behind the same Traefik+Authentik forward-auth as Wing.
  The node BFF (`src/hooks.server.ts`) reads `X-Authentik-*` exactly like `ForwardAuthUserStorage.php`,
  and **enforces an edge-token** (mirrors Wing's `X-Wing-Edge-Token`) so a loopback caller can't
  spoof identity headers.
- **App catalog & consolidation.** Standardize on `/api/v1/hub/systems` + hub-cards. Retire the two
  parallel launchers — Puter's SQLite start-menu (`roles/pazny.puter/tasks/apps.yml`) and the IIAB
  TUI config — onto this one feed.
- **App embedding.** iframe the already-routed + Authentik-gated services. "grafana face" = Grafana
  HTTP API + kiosk-mode panels.
- **Files (the one new backend).** A thin VFS API scoped to `tenants/<slug>/users/<uid>/` with
  **realpath-∈-scope containment** (reuse AgentKit's gating): `list/stat/read/write/mkdir/move/
  upload/download`. Hosted in **Bone** (FastAPI; already the state/dispatcher, already touches the
  FS, JWT-scope auth), mirrored to Wing for audit. File-picker-as-a-service = a shell dialog other
  apps invoke via `postMessage`, two modes: *from nOS* (VFS) or *from device* (upload into VFS).
- **Install / agent-built apps.** Author `apps/<name>.yml` → apps_runner gives route+gate+registry+
  hub tile+GDPR. For agents: extend the `MigrationWriteTool` gated-write pattern to `apps/<name>.yml`
  + scaffold a **private submodule** (docs + code + migrations + idempotent DB/schema/PHP-site/next.js
  commands, default tier-3, promotable). The `nos-face` repo carries the linter + programmatic harness
  the app-builder agent targets. The apps_runner `wing_system` + hub tile *is* the companion-app surface.

## Milestones (M1 first — it proves the whole spine cheaply)

- **M0 — scaffold + framework spike.** `thisisait/nos-face` + skeletal `roles/pazny.face`
  (clone→build→route→gate→health), mirroring `roles/pazny.keap`. Framework: **SvelteKit**
  (`macos-web` is Svelte; light; embed-heavy shell). Edge-token trust wired. **`install_face`
  default `false`** — opt-in until mature.
- **M1 — walking skeleton.** Desktop that: (1) lists `/hub` apps from `GET /api/v1/hub/systems`;
  (2) opens one app in an iframe window (Grafana); (3) inherits SSO (no login, shows the Authentik
  username); (4) browses one real folder (`users/<uid>/documents`) via the new VFS `list`. Validates
  identity + catalog + embed + files end-to-end.
- **M2 — file surface.** Full VFS API + file-browser app + file-picker-as-a-service (two-mode) +
  document open via Nextcloud→euro-office on the real tree. Nextcloud becomes the class-3 document
  producer feeding KEAP; Puter leaves the document flow.
- **M3 — app-host + system apps.** iframe app framework + "install system application" + grafana-face
  (Grafana API kiosk panels) + consolidate control planes (Authentik/Wing/KEAP/Infisical/Nextcloud).
- **M4 — agent app-builder.** `nos-face` linter+harness+doctrine; AgentKit `AppScaffoldTool` (gated)
  scaffolds a user-app private submodule + companion app. Target: near-one-shot hotel ordering system.
- **M5 — TUI parity + Puter retirement.** Evolve the IIAB Textual TUI onto the same catalog + VFS APIs
  (the "TUI nOS face"); retire Puter as the face (keep only as an installable app). Harden AgentKit.

## Files (nOS side)

- `roles/pazny.face/` — `defaults/main.yml`, `tasks/main.yml`, `templates/compose.yml.j2`, `meta/`,
  `handlers/`. Pattern-mirrors `roles/pazny.keap/`.
- `files/anatomy/plugins/face-base/plugin.yml` — `authentik` (forward_auth), `hub_card`, `notification`, `requires`.
- `state/manifest.yml` — a `face` row (`domain_var: face_domain`, `port_var: face_port`).
- `default.config.yml` — `install_face` (false), `face_repo_ref`, `face_domain`, `face_port`, edge-token, VFS vars.
- `files/anatomy/bone/` — new `vfs` module (M2), scoped to `users/<uid>/`, realpath-contained; re-export OpenAPI.
- `docs/doctrine/filesystem.md` — correction: Puter is class-1; the face file-browser reads the class-3 tree.

## Verification

- **M1 spine:** load `face.<tld>` behind Authentik → desktop renders + shows the Authentik username;
  dock list matches `GET /api/v1/hub/systems`; a Grafana iframe window opens; VFS `list` of
  `users/<uid>/documents` matches `ls` on disk. Playwright journey under `tests/e2e/`.
- **Edge-trust:** direct loopback with forged `X-Authentik-*` but no edge token → refused.
- **VFS containment:** a `../` escape → 403; a realpath-∈-scope unit gate.
- **Reproducibility:** `face_repo_ref` pinned; `roles/pazny.face` re-converge is `changed=0`; skipped when `install_face=false`.

## Risks & guardrails

- **Header spoofing** → enforce the edge-token exactly like Wing (non-negotiable).
- **macOS = structure-only isolation** (real per-uid 0700 is Linux-only) → the VFS scope check must
  enforce the per-uid path regardless (real-server-ready).
- **Scope creep** → M1 walking skeleton before any WM polish.
- **Don't destabilize the release** → `nos-face` is a new opt-in service (`install_face` default false);
  Puter untouched; the safe Puter pin (#1) + health probe (#3) can still ship independently.

## To settle at M0

- VFS host: **Bone** (recommended) vs Wing.
- face auth: pure `forward_auth` gate (BFF reads headers) vs `header_oidc`.
