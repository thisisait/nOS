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

export type ColumnKind = 'text' | 'number' | 'boolean' | 'date' | 'select' | 'json' | 'user';

export interface ColumnSpec {
	key: string;
	label: string;
	kind: ColumnKind;
	options?: string[];
	required?: boolean;
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
}

// ── Catalog (Wing /hub/systems) ───────────────────────────────────────────────

export interface HubApp {
	slug: string;
	title: string;
	icon: string;
	url: string;
	description: string;
	tier: number;
	/** true once the app is a nos-native (API-calling) app rather than an iframe. */
	native?: boolean;
}
