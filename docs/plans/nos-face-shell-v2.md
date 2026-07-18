# nOS face — shell v2 (dataTable-driven WM + control panel)

> Design captured from operator feedback 2026-07-18. The shell's chrome, layouts,
> wallpapers, control panel, and window positions all become **dataTable-driven**:
> repo carries the defaults (SoC), a DataTable is the runtime catalog (user-addable),
> and per-user state persists (survives restart). Companion: `docs/plans/nos-face.md`,
> `docs/plans/keap-datatables-apps-systems.md` (the DataTable substrate).

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
