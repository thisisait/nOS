# nOS face — shell v2 (dataTable-driven WM + control panel)

> Design captured from operator feedback 2026-07-18. The shell's chrome, layouts,
> wallpapers, control panel, and window positions all become **dataTable-driven**:
> repo carries the defaults (SoC), a DataTable is the runtime catalog (user-addable),
> and per-user state persists (survives restart). Companion: `docs/plans/nos-face.md`,
> `docs/plans/keap-datatables-apps-systems.md` (the DataTable substrate).

## Status — shell v0.3 (2026-07-18, live)

Second operator round on the deployed v0.2 surfaced four real bugs + two feature
gaps. Fixed/shipped (vendored `files/anatomy/face`, `VERSION` 0.3.0):

- **Window controls fixed** — the traffic-light clicks were stolen by the titlebar
  `setPointerCapture` (the drag). `stopPropagation` on the lights + a button-origin
  guard on the titlebar drag. (v0.1 regression that returned in the rebuild.)
- **File explorer fixed (root cause: native-app remount)** — rendering the native
  component inline as `{#await resolveNativeComponent(win.app)}` created a fresh
  promise on every store update (focus on pointerdown), so `{#await}` tore down and
  remounted the app on every interaction — the click was lost and the app reset to
  its root. New `NativeHost.svelte` resolves the component **once** into stable state.
- **No more infinite windows** — dock/palette launches are **singleton** (`focusApp`
  focuses an open window instead of spawning a duplicate).
- **Taskbar** — bottom-left strip: open-window **count** + a chip per window →
  click focuses/restores, ✕ closes. (Live thumbnails = follow-up.)
- **Live split + ratio gutter** — `◨ Split` tiles the two front windows left|right;
  a draggable middle **divider** re-allocates the ratio live (`lib/wm/split.ts` +
  `TileDivider.svelte`). The fixed drag-to-top snap layouts (single/halves/thirds/2×2)
  stay; this adds the adjustable two-up the operator asked for.
- **Command palette (Ctrl+Space, hold 2s)** — Raycast-style launcher + WM actions
  (Control Panel / Split) **and** a local-LLM "ask" (`/bff/ask` → host Ollama MLX,
  loopback; model auto-picked from the installed set, honest "not configured" when
  none). **Running arbitrary host commands is deliberately NOT wired** — that needs
  a gated, allowlisted, audited Bone endpoint (destructive-op safety doctrine).

### Still open (next)
- **Live window thumbnails** in the taskbar (canvas snapshots).
- **Divider for thirds/2×2** (only the two-up half split has a live gutter today).
- **Palette command-exec** behind a gated/audited Bone allowlist surface.
- **KEAP config DataTables** live-wiring — blocked on a KEAP `/agent/v1/tables`
  bearer write route (the seeder no-ops until then; shell runs on repo defaults +
  user-state). See `docs/plans/keap-datatables-apps-systems.md`.

## The SoC → dataTable → user-state pattern (load-bearing)

Every configurable surface follows the same three layers:

1. **Repo (SoC)** — the defaults live in code (`nos-face` repo): the built-in layouts,
   wallpapers, and control-panel entries. Version-controlled, reviewable, seeded.
2. **Runtime DataTable** — a KEAP DataTable is the live catalog = repo defaults (system rows)
   **+ user additions** (user rows). Rendered by the generic `DataTableApp` component. A user
   adds a new layout / wallpaper by adding a row (rawDataTable form today).
3. **Per-user state** — the user's *selections* (active wallpaper, custom layouts, window
   positions) live in the Bone **user-state** KV (class-3, persistent → **survives restart**,
   backed up with the tenant tree). Never in the repo.

This is exactly the app-tier doctrine (`face-app-tiers.md`) applied to the shell itself: the
shell is its own first set of F1 apps.

## Surfaces to build

### 1. Window manager v2 — snap / tiling
- **Drag → snap dropzone**: while dragging a window, show a small dropzone at the top edge;
  on hover it grows; it reveals the **layout cells** of the active layout; hovering a cell
  highlights it; dropping snaps the window into that cell → **multitask/tiled mode**.
- **Layouts DataTable** (`face.layouts`): rows = named layouts with a cell grid spec
  (`half-v`, `half-h`, `thirds`, `2x2`, …). Repo seeds the built-ins; users add rows.
  A layout row = `{ name, cells: [{x,y,w,h} in fractions], icon }`.
- **Resize/zoom/controls**: shipped in v1 (traffic lights, green=maximize, bottom-right grip,
  drag-select guard). Snap builds on top.

### 2. Control Panel — the first DataTable, as an icon grid
- **System configuration is a DataTable** rendered NOT as a grid/gallery but as a **control-panel
  icon grid** (a new view mode or a dedicated component). Each row = a config surface
  (Wallpaper, Layouts, Identity, Storage, …). Clicking a row **opens a window** (not a modal)
  — for now the window hosts the row in `rawDataTable`; later a bespoke editor.
- Rows link through to their editor (rawDataTable initially).

### 3. Wallpapers — DataTable-driven
- **Wallpapers DataTable** (`face.wallpapers`): repo seeds `aurora/graphite/sunset/forest`;
  users add rows (gradient spec or an uploaded image ref via the VFS). The Settings/Control-Panel
  wallpaper picker reads this table; the active choice persists in user-state (`face.desktop/prefs`).

### 4. Window positions — cached per device viewport
- Persist window geometry **keyed by viewport size** so each device restores its own layout:
  user-state ns `face.windows`, key = `"<w>x<h>"` (bucketed), value = `[{id,x,y,w,h,z,min}]`.
- **Debounced 30s** writes (don't spam Bone on every drag). Restore on desktop mount for the
  current viewport bucket; fall back to cascade for an unseen viewport.

## Backup / durability
User edits are class-3 per-user state (`users/<uid>/.face/state.db` + any wallpaper uploads under
`users/<uid>/`), already covered by the tenant backup. Nothing user-authored lives in the repo.
The KEAP config DataTables (layouts/wallpapers/controls) persist in `keap.db` (class-1, backed up).

## Build order (proposed)
1. **Window-position caching** (user-state, 30s debounce) — immediate quality-of-life, low risk.
2. **Wallpapers + Layouts DataTables** (repo seed + user-state selection) — unlocks the pattern.
3. **Snap/tiling WM** (dropzone → layout cells → tiled mode) — the flashy one.
4. **Control Panel** (DataTable-as-icon-grid, rows open windows) — consolidates settings.
5. Wire all config DataTables to the live KEAP `/api/tables` (with the BFF proxy) once that
   surface + the agent route land — until then they can seed from repo + user-state.

## Open question for the operator
- **Config DataTables home**: KEAP (`/api/tables`, shared catalog, rendered in /explore too) vs a
  face-local store. KEAP is the consistent choice (everything-is-a-dataTable), but couples the
  shell to KEAP being up. A thin fallback (repo defaults + user-state) keeps the desktop usable
  if KEAP is down. Recommend: **KEAP as source of truth + repo/user-state fallback.**
