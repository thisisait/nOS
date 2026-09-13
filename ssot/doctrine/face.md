# nOS-face Doctrine

> Canonical decisions for the nOS face (the web-desktop shell). Detail:
> [`docs/archive/nos-face.md`](../../docs/archive/nos-face.md) +
> [`docs/archive/nos-face-shell-v2.md`](../../docs/archive/nos-face-shell-v2.md).
> Companion: [`face-app-tiers.md`](face-app-tiers.md),
> [`filesystem.md`](filesystem.md).
> Numbered headings are the addresses; citations elsewhere keep `§N`.

## 1. Vendored, not forked

The shell source SHALL live in-repo at `files/anatomy/face/` (2026-07-18, v0.2),
joining wing/bone/pulse as an in-tree anatomy organ. The separate-repo
(`thisisait/nos-face`) pinned-tag clone model is retired — reproducibility is
the repo commit (`VERSION` tracks the shell version). `roles/pazny.face` SHALL
sync the vendored tree into the build dir; `docker compose` builds `nos/face`
from it (keap build-from-source precedent).

## 2. A shell over an OS that already exists

face SHALL compose surfaces nOS already owns. It MUST NOT reimplement an OS.
Identity = Authentik forward-auth; catalog = Wing `/api/v1/hub/systems`;
files = Bone VFS over the real per-user tree; config = KEAP DataTables.

## 3. Identity is free and never invented

The BFF (`src/hooks.server.ts`) SHALL build the per-user identity from
`X-Authentik-*` headers and MUST trust them only when the request also carries
`X-Face-Edge-Token` (the Traefik `face-edge` middleware — mirrors Wing SEC-6).
SEC-02: the container MUST join only the Traefik `gated_net`. `uid` SHALL be
pinned server-side from the edge-trusted identity and is the one per-user
partition key end-to-end (VFS path, user-state DB, KEAP row visibility). The
browser MUST NOT set `uid`. Tokens (Bone VFS, Wing edge, KEAP) MUST live only
in `$lib/server/*`, never shipped to the client.

## 4. Three-layer config

Every configurable surface — layouts, wallpapers, control-panel entries,
window positions — SHALL follow the same layers:

1. **Repo (SoC)** — built-in defaults are code in `files/anatomy/face/`
   (reviewed, seeded).
2. **Runtime DataTable** — a KEAP DataTable (`face.layouts|wallpapers|controls`)
   = repo system-rows + user-added rows. KEAP `/api/tables` is the source of
   truth, with a repo-defaults + user-state fallback so the desktop stays
   usable when KEAP is down. A usable desktop MUST NOT couple to KEAP uptime.
3. **Per-user state** — the user's *selections* (active wallpaper, window
   geometry per viewport bucket `"<w>x<h>"`, debounced 30 s) persist in Bone
   user-state (`.face/state.db`, class-3, survives restart). They MUST NOT
   live in the repo.

## 5. Native over iframe

Most services cannot be iframed. The primary app surface SHALL be nos-native
apps that call the nOS APIs (Tier F1 — a Svelte component + a namespaced
API/user-state contract, no iframe). iframe embedding MAY remain only for
services that genuinely support it.

## 6. Hard input safety

- **XSS:** components auto-escape (`{expr}`). `{@html}` and any unescaped
  injection MUST NOT appear in the shell — pinned by
  `tests/anatomy/test_face_security_gates.py`.
- **Filenames / real FS:** Bone MUST contain every path by realpath-∈-scope
  AND sanitize every new leaf (NFC-normalize; reject NUL/control/BiDi/zero-width,
  path separators, reserved names, trailing dot/space, overlong).
  Malformed/traversal input → 400/403, never an escape. UTF-8 is exact on
  read/write.
- **Shared data:** user-state values SHALL be small structured JSON (≤256 KB),
  namespace/key regex-gated.

## 7. The enforcement triplet

This wiring is doctrine, enforced by: this file →
`tools/face-wiring-report.py --strict` (linter) → `tests/anatomy/test_face_*.py`
(CI pytest gates). Changing the wiring MUST update all three.
