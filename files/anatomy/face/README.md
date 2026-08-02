# nOS face — the unified web-desktop shell

The "not-quite-OS" web-desktop, **vendored into the nOS monorepo** (2026-07-18, v0.2)
alongside wing/bone/pulse. `roles/pazny.face` builds this directory with `docker compose`.
Design: [`docs/plans/nos-face.md`](../../../docs/plans/nos-face.md),
[`docs/archive/nos-face-shell-v2.md`](../../../docs/archive/nos-face-shell-v2.md); hard doctrine:
[`docs/doctrine/face.md`](../../../docs/doctrine/face.md) (Wave-2 G6).

## Stack

SvelteKit 2 + Svelte 5 (runes) + `adapter-node`. The node server IS the **BFF**: it reads the
Authentik forward-auth headers, enforces the `X-Face-Edge-Token` (anti-spoof, mirrors Wing SEC-6),
pins `uid`, and holds the Bone/Wing/KEAP tokens the browser never sees.

## The load-bearing pattern (SoC → DataTable → user-state)

- **Repo (SoC)** — built-in layouts/wallpapers/control entries live here as code.
- **Runtime DataTable** — a KEAP DataTable (`face.layouts|wallpapers|controls`) = repo rows + user
  rows, rendered by `DataTableApp`. KEAP is the source of truth; `/bff/tables` falls back to repo
  defaults + user-state when KEAP is down.
- **Per-user state** — selections (active wallpaper, window geometry per viewport) persist in Bone
  user-state (`.face/state.db`) via `$lib/api/userstate`.

## Layout (frozen Wave-0 seams — do not rename)

- `src/hooks.server.ts` — the BFF identity + edge-trust boundary.
- `src/lib/contracts/` — shared types (WindowModel, LayoutSpec, WallpaperSpec, ControlEntry, …).
- `src/lib/server/upstream.ts` — server-only Bone/Wing/KEAP clients (tokens live here).
- `src/lib/api/` — browser → BFF clients (userstate/vfs/hub/tables).
- `src/lib/stores/desktop.ts` — window/z-order state + the `useSnapEngine`/`usePersistence`
  extension points Wave-1 groups attach to.
- `src/routes/bff/*` — the BFF endpoints; `/health` is the liveness probe.

## Dev

```bash
npm install
npm run dev       # local (no edge token → trust implicit)
npm run check     # svelte-check
npm run lint      # prettier + eslint
npm test          # vitest
npm run build     # adapter-node → build/
```

## Security invariants (pinned by tests/anatomy/test_face_*.py in Wave 2)

- `uid` is never read from the browser — only from the edge-trusted identity.
- No `{@html}` / raw HTML injection in components (Svelte auto-escapes `{expr}`).
- The VFS/user-state tokens live only in `$lib/server/*`, never shipped to the client.
