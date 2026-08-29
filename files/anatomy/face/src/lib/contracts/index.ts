/**
 * nOS-face shared contracts — the FROZEN seam (Wave 0).
 *
 * These types are the coordination boundary between the parallel Wave-1 feature
 * groups (WM snap/tiling, control-panel, wallpapers, per-viewport cache, native
 * apps, config DataTables). Changing a type here ripples across worktrees, so it
 * is deliberately small and stable. Add fields; avoid renaming.
 *
 * Load-bearing doctrine (docs/doctrine/face-app-tiers.md, nos-face-shell-v2.md):
 *   SoC (repo defaults) → runtime DataTable (user-addable) → per-user state.
 */

// ── The app axes: form (what it IS), build (what it COSTS) ───────────────────

/**
 * `form`, `build` and `layer` are FACETS OF ONE ENTITY, and their vocabulary
 * lives in `state/genome/entity.schema.json` (`definitions.axes`) — generated
 * into this directory as `entity.gen.ts` and into
 * `files/anatomy/module_utils/nos_entity.py` by `tools/genome-codegen.py`.
 * This module re-exports them so `$lib/contracts` stays the shell's one import
 * surface; it does NOT restate the values, because restating them is the exact
 * defect R4 closed.
 *
 * Until 2026-08-07 the two app axes were TypeScript unions declared here, the
 * `layer` axis was four string literals inside `tools/anatomy-graph-gen.py`,
 * and the compiler that harvests this registry validated neither — a typo'd
 * `form: 'veiw'` became a fourth form in the estate's address space with no
 * gate able to see it. One declaration, two runtimes, one emitter.
 *
 *   view    — a full window over estate data (Anatomy, Tables, Explore, Files)
 *   utility — a focused tool with its own state (empty set today; the doctrine
 *             names Sticky Notes and this shell has no such app)
 *   widget  — a small surface that lives inside another; NOT a window
 *   frame   — a service rendered in an iframe (the hub catalog)
 *
 * WHY `form` REPLACED A BOOLEAN. The shell used to record one binary —
 * `isNativeApp(slug)`, "a nos-native API-calling app rather than an iframe" —
 * and `HubApp.native?: boolean`, a field nothing in this repo ever set or
 * read (measured 2026-08-07: zero producers, zero consumers). A binary can
 * answer "does this get a component or an iframe" and nothing else, so the
 * moment a third kind of surface existed — a widget, which is native AND not
 * a window — the binary had no value for it. `form` is the axis; the boolean
 * was a projection of it onto two points.
 *
 * `build` (F1–F4/H, `docs/doctrine/face-app-tiers.md`) is INDEPENDENT of
 * `form` and only loosely correlated: a frame is usually the cheapest thing to
 * build and a view usually is not, but that is a tendency, not a definition.
 * Nothing in this shell derives either axis from the other — pinned by
 * `tests/anatomy/test_face_app_form_axis.py`.
 */
export type { AppForm, AppBuild, ServiceLayer } from './entity.gen';
export { APP_FORMS, APP_BUILDS, SERVICE_LAYERS, AXES } from './entity.gen';

// ── Identity (BFF-derived, edge-trusted) ─────────────────────────────────────

/** The per-user identity the BFF builds from Authentik forward-auth headers.
 *  `uid` is the ONLY per-user partition key end-to-end (VFS path, user-state DB,
 *  KEAP row visibility). Never invented; never read from the browser. */
export interface Identity {
	uid: string;
	username: string;
	email: string;
	/** Authentik groups → RBAC tier rank (nos-admins … nos-guests). */
	groups: string[];
	/** True once the BFF has verified BOTH the edge token and a non-empty uid. */
	authenticated: boolean;
}

export const ANON: Identity = {
	uid: '',
	username: '',
	email: '',
	groups: [],
	authenticated: false
};

// ── Window model (shared by WM v2 snap + per-viewport cache) ──────────────────

/** A live desktop window. Geometry is in CSS pixels; persistence buckets by
 *  viewport (see WindowGeometry / face.windows). */
export interface WindowModel {
	id: string;
	/** App slug that owns this window (native app or catalog/iframe app). */
	app: string;
	title: string;
	x: number;
	y: number;
	w: number;
	h: number;
	z: number;
	min: boolean;
	max: boolean;
	/** Set when the window is snapped into a layout cell (tiled mode). */
	snappedCell?: string;
	/** For a service window: the URL rendered via ServiceFrame (iframe or open-↗). */
	url?: string;
	/** Operator's embeddability declaration (from the hub_card). undefined =
	 *  attempt inline; false = X-Frame-Options-blocked → open-↗ card. */
	embed?: boolean;
}

/** The subset persisted to user-state, keyed by viewport bucket "<w>x<h>". */
export interface WindowGeometry {
	id: string;
	app: string;
	x: number;
	y: number;
	w: number;
	h: number;
	z: number;
	min: boolean;
	snappedCell?: string;
	url?: string;
	embed?: boolean;
}

// ── Layouts (face-layouts DataTable → snap cells) ─────────────────────────────

/** One tiling cell, in fractions of the desktop work area [0..1]. */
export interface LayoutCellSpec {
	id: string;
	x: number;
	y: number;
	w: number;
	h: number;
}

/** A named tiling layout. Repo seeds the built-ins; users add rows. */
export interface LayoutSpec {
	slug: string;
	name: string;
	icon: string;
	cells: LayoutCellSpec[];
	/** true = a repo/system default row; false = a user-added row. */
	system: boolean;
}

// ── Wallpapers (face-wallpapers DataTable) ────────────────────────────────────

export type WallpaperKind = 'gradient' | 'image';

/** A wallpaper. Gradient = a CSS gradient spec; image = a VFS-relative path the
 *  BFF streams. Repo seeds aurora/graphite/sunset/forest; users add rows. */
export interface WallpaperSpec {
	slug: string;
	name: string;
	kind: WallpaperKind;
	/** For kind=gradient: a safe CSS gradient string (validated server-side). */
	gradient?: string;
	/** For kind=image: a VFS-relative path under the user's tree. */
	vfsPath?: string;
	system: boolean;
}

// ── Control panel (face-controls DataTable → icon grid) ───────────────────────

/** One control-panel surface. Clicking a row OPENS A WINDOW (not a modal) that
 *  hosts the surface — a rawDataTable initially, a bespoke editor later. */
export interface ControlEntry {
	slug: string;
	name: string;
	icon: string;
	/** Which surface the window hosts: a known editor key, or a table slug. */
	surface: 'wallpaper' | 'layouts' | 'identity' | 'storage' | 'rawDataTable';
	/** For surface=rawDataTable: the DataTable slug to render. */
	table?: string;
	system: boolean;
}

// ── Generic DataTable (mirrors the KEAP contract, minimally) ──────────────────

export type ColumnKind =
	| 'text'
	| 'number'
	| 'boolean'
	| 'date'
	| 'select'
	| 'json'
	| 'user'
	| 'taxonomyRef'
	| 'objectRef'
	| 'file'
	| 'vector';

export interface ColumnSpec {
	key: string;
	label: string;
	kind: ColumnKind;
	options?: string[];
	required?: boolean;
	/** OLAP role (dimension/measure/attribute) — metadata, not enforced here. */
	role?: string;
	/** vector column dimensionality (Pulse-generated brain-embedding). */
	dim?: number;
	unit?: string;
}

/** A DataTable row as the shell sees it: an id + a flat bag of cell values. */
export interface DataTableRow {
	id: string;
	[key: string]: unknown;
}

export interface DataTable {
	slug: string;
	title: string;
	columns: ColumnSpec[];
	rows: DataTableRow[];
	/** Where the rows came from — drives the "KEAP down" fallback banner. */
	source: 'keap' | 'fallback';
	/** Server-derived: may the current caller write rows (manager+ tier AND a RW
	 *  token is configured)? Drives whether the editor shows Add/Edit. Never trust
	 *  a client-set value — this is set by the BFF from the edge-trusted identity. */
	canWrite?: boolean;
	/** How the table asks to be rendered (KEAP `view` block). Absent = grid,
	 *  byte-identical to before this existed. Declared ON THE TABLE because
	 *  "spreadsheet or article list" is a property of the data, not of this
	 *  client — a `research` column holding paragraphs is unreadable in a
	 *  nowrap grid, and that is knowable once rather than per surface. */
	view?: TableView;
}

/** The comparison vocabulary. Not invented here — it is KEAP's `filterOpSchema`
 *  (shared/contracts/table.ts), already validated author-side, so a predicate
 *  written for a view block and one written for a query mean the same thing. */
export type RowOp = 'eq' | 'neq' | 'lt' | 'lte' | 'gt' | 'gte' | 'contains';

/** One comparison against one column. Scalars only — a predicate that could
 *  carry an object is a predicate that could carry markup. */
export interface RowPredicate {
	column: string;
	op: RowOp;
	value: string | number | boolean;
}

/** A named class of rows worth jumping to. Predicates AND together. */
export interface HighlightSpec {
	label: string;
	when: RowPredicate[];
}

/**
 * A suggested next step, offered when `when` matches.
 *
 * `action` is an ID FROM A CLOSED CATALOG THE RENDERER OWNS (`VIEW_ACTIONS` in
 * `$lib/tables/view`), never a command, URL or handler. This is the genome's
 * own rule pointed at the face: `state/genome/entity.schema.json` keeps opcodes
 * and handlers as code "per runtime, hash-compared", precisely so a capability
 * cannot be added by data. A table — or a model filling this block — may say
 * WHICH of the things this renderer can already do is worth doing. It may not
 * teach it a new one.
 */
export interface OfferSpec {
	label: string;
	action: string;
	/** REQUIRED, unlike a highlight's — an offer that is always on is not an
	 *  offer, it is a button, and a suggestion that appears when it cannot help
	 *  is how a surface stops being read. */
	when: RowPredicate[];
}

/**
 * Render style + the columns each one needs. Mirrors KEAP's `viewMetaSchema`
 * (shared/contracts/table.ts) — KEAP validates, this only renders.
 *
 * `facets` / `highlights` / `offer` are the generative-UI seam (2026-08-28).
 * They name COLUMN KEYS, COMPARISON OPS AND LABELS — nothing about chips, tabs,
 * pixels, DOM or Svelte — which is what makes one declaration inheritable by a
 * future native renderer reading the identical JSON from KEAP's
 * `GET /agent/v1/tables/:slug`. It decides for itself whether a facet is a
 * `<select>`, a segmented control or an `NSPopUpButton`.
 *
 * All three are OPTIONAL and absent means byte-identical to the render before
 * they existed. They are filled by an author today and may be filled by a model
 * tomorrow — same block, same door (`narrowView`), same degrade.
 */
export interface TableView {
	style: 'grid' | 'blog' | 'timeline' | 'tiles';
	titleColumn?: string;
	bodyColumn?: string;
	dateColumn?: string;
	mediaColumn?: string;
	metaColumns?: string[];
	/** ≤2 column keys, outer→inner. "Two levels" is `facets.length === 2`, not a
	 *  nesting structure — a renderer that only affords one honours the first. */
	facets?: string[];
	/** ≤4 row classes for fast navigation. */
	highlights?: HighlightSpec[];
	/** ≤1. See OfferSpec — the action is chosen from the renderer's catalog. */
	offer?: OfferSpec;
}

// ── Catalog (Wing /hub/systems) ───────────────────────────────────────────────

export interface HubApp {
	slug: string;
	title: string;
	icon: string;
	url: string;
	description: string;
	tier: number;
	/** NO `form` FIELD, deliberately. A hub catalog entry's form is `frame` by
	 *  construction — the shell renders every one of them through
	 *  `ServiceFrame` (`src/routes/+page.svelte`) — so the fact is a property
	 *  of the render path, not something the catalog declares. The shell
	 *  registers them as frames on load (`registerHubFrames`), which is where
	 *  the count comes from. The field this replaced (`native?: boolean`) had
	 *  zero producers and zero consumers for its whole life. */
	/** Operator-declared embeddability (hub_card). undefined = attempt inline;
	 *  false = the service sets X-Frame-Options → render an open-↗ card instead. */
	embed?: boolean;
}
