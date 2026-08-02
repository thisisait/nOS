# nOS-face Doctrine

> Canonical decisions for the nOS face (the web-desktop shell). Detail: `docs/archive/nos-face.md`
> + `docs/archive/nos-face-shell-v2.md`. Companion: `face-app-tiers.md`, `filesystem.md`.

**Vendored, not forked.** The shell source lives IN-REPO at `files/anatomy/face/` (2026-07-18, v0.2),
joining wing/bone/pulse as an in-tree anatomy organ. The separate-repo (`thisisait/nos-face`) pinned-tag
clone model is **retired** — reproducibility is now the repo commit itself (the `VERSION` marker tracks
the shell version). `roles/pazny.face` **syncs** the vendored tree into the build dir; `docker compose`
builds `nos/face` from it (keap build-from-source precedent).

**A shell over an OS that already exists.** face composes surfaces nOS already owns — it does NOT
reimplement an OS. Identity = Authentik forward-auth; catalog = Wing `/api/v1/hub/systems`; files = Bone
VFS over the real per-user tree; config = KEAP DataTables.

**Identity is free and never invented (the non-negotiable).** The BFF (`src/hooks.server.ts`) builds the
per-user identity from `X-Authentik-*` headers and trusts them **only** when the request also carries
`X-Face-Edge-Token` (the Traefik `face-edge` middleware — mirrors Wing SEC-6). SEC-02: the container
joins ONLY the Traefik `gated_net`. `uid` is **pinned server-side** from the edge-trusted identity and is
the ONE per-user partition key end-to-end (VFS path, user-state DB, KEAP row visibility). The browser can
NEVER set `uid`. Tokens (Bone VFS, Wing edge, KEAP) live only in `$lib/server/*`, never shipped to the client.

**The three-layer config pattern (SoC → DataTable → user-state).** Every configurable surface —
layouts, wallpapers, control-panel entries, window positions — follows the same layers:
1. **Repo (SoC)** — built-in defaults are code in `files/anatomy/face/` (reviewed, seeded).
2. **Runtime DataTable** — a KEAP DataTable (`face.layouts|wallpapers|controls`) = repo system-rows +
   user-added rows. **KEAP `/api/tables` is the source of truth**, with a **repo-defaults + user-state
   fallback** so the desktop stays usable when KEAP is down. Never couple a usable desktop to KEAP uptime.
3. **Per-user state** — the user's *selections* (active wallpaper, window geometry per viewport bucket
   `"<w>x<h>"`, debounced 30 s) persist in Bone user-state (`.face/state.db`, class-3, survives restart).
   Never in the repo.

**Native over iframe.** Most services cannot be iframed. The primary app surface is **nos-native apps
that call the nOS APIs** (Tier F1 — a Svelte component + a namespaced API/user-state contract, no iframe).
iframe embedding remains only for services that genuinely support it.

**Hard input safety (bulletproofing).**
- **XSS:** components auto-escape (`{expr}`). `{@html}` and any unescaped injection are **forbidden** in
  the shell — pinned by `tests/anatomy/test_face_security_gates.py`.
- **Filenames / real FS:** Bone contains every path by realpath-∈-scope AND sanitizes every new leaf
  (NFC-normalize; reject NUL/control/BiDi/zero-width, path separators, reserved names, trailing dot/space,
  overlong). Malformed/traversal input → 400/403, never an escape. UTF-8 is exact on read/write.
- **Shared data:** user-state values are small structured JSON (≤256 KB), namespace/key regex-gated.

**The enforcement triplet.** This wiring is doctrine, enforced by: this file → `tools/face-wiring-report.py
--strict` (linter) → `tests/anatomy/test_face_*.py` (CI `pytest` gates). Changing the wiring means updating
all three.
