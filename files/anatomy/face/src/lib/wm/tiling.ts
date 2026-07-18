/**
 * WM v2 · grid tiling with live gutters (generalizes the two-up split).
 *
 * A tiling session lays the front-most windows into the cells of a grid whose
 * COLUMN and ROW fractions are adjustable via draggable gutters:
 *   • half-v  → 2 cols × 1 row  (1 vertical gutter)
 *   • thirds  → 3 cols × 1 row  (2 vertical gutters)
 *   • 2x2     → 2 cols × 2 rows (1 vertical + 1 horizontal gutter — a cross)
 * Dragging a gutter re-allocates the two tracks it separates (their sum is
 * preserved) and re-tiles live. Geometry flows through the store's setGeometry
 * so the G4 per-viewport cache persists it like any move/resize.
 *
 * Pure logic (fraction math + clamping) is exported for unit tests; only
 * `retile`/`applyTiling` touch the live viewport.
 */
import { writable, get, derived, type Readable } from 'svelte/store';
import { windows, setGeometry } from '$lib/stores/desktop';

/** Desktop menubar height; the work area starts below it. */
export const MENUBAR = 28;
/** Minimum track fraction so no pane collapses under a gutter drag. */
export const MIN_TRACK = 0.12;

export type TileMode = 'half-v' | 'thirds' | '2x2';

export interface TilingState {
	mode: TileMode | null;
	/** Column fractions (sum 1). */
	cols: number[];
	/** Row fractions (sum 1). */
	rows: number[];
	/** Window id per cell, row-major (length = cols·rows; '' = empty cell). */
	cells: string[];
}

const EMPTY: TilingState = { mode: null, cols: [], rows: [], cells: [] };
export const tiling = writable<TilingState>({ ...EMPTY });

/** True while a tiling session is active (for menubar/gutter gating). */
export const tilingActive: Readable<boolean> = derived(tiling, ($t) => $t.mode !== null);

const DEFAULTS: Record<TileMode, { cols: number[]; rows: number[] }> = {
	'half-v': { cols: [0.5, 0.5], rows: [1] },
	thirds: { cols: [1 / 3, 1 / 3, 1 / 3], rows: [1] },
	'2x2': { cols: [0.5, 0.5], rows: [0.5, 0.5] }
};

// ── pure fraction math (unit-tested) ─────────────────────────────────────────

/** Cumulative start fraction of each track: [0, f0, f0+f1, …]. */
export function prefix(fracs: number[]): number[] {
	const out = [0];
	for (let i = 0; i < fracs.length - 1; i++) out.push(out[i] + fracs[i]);
	return out;
}

/** Move the boundary between track `i` and `i+1` to cumulative fraction `frac`,
 *  preserving the pair's combined span and clamping so neither drops below
 *  MIN_TRACK. Returns a new fractions array. */
export function moveBoundary(fracs: number[], i: number, frac: number): number[] {
	if (i < 0 || i + 1 >= fracs.length) return fracs;
	const start = prefix(fracs)[i]; // cumulative before track i
	const span = fracs[i] + fracs[i + 1];
	const end = start + span;
	const f = Math.min(end - MIN_TRACK, Math.max(start + MIN_TRACK, frac));
	const next = [...fracs];
	next[i] = f - start;
	next[i + 1] = end - f;
	return next;
}

/** Pixel rect for cell (col c, row r) in a work area, from the track fractions. */
export function cellRect(
	cols: number[],
	rows: number[],
	c: number,
	r: number,
	area: { w: number; h: number }
): { x: number; y: number; w: number; h: number } {
	const cx = prefix(cols);
	const ry = prefix(rows);
	return {
		x: Math.round(cx[c] * area.w),
		y: MENUBAR + Math.round(ry[r] * area.h),
		w: Math.round(cols[c] * area.w),
		h: Math.round(rows[r] * area.h)
	};
}

// ── live application ─────────────────────────────────────────────────────────

function workArea(): { w: number; h: number } {
	const w = typeof window !== 'undefined' ? window.innerWidth : 1280;
	const vh = typeof window !== 'undefined' ? window.innerHeight : 800;
	return { w, h: Math.max(120, vh - MENUBAR) };
}

/** Re-apply geometry for every assigned, still-open window. Ends the session if
 *  no assigned window remains. */
export function retile(): void {
	const t = get(tiling);
	if (!t.mode) return;
	const list = get(windows);
	if (!t.cells.some((id) => id && list.some((w) => w.id === id))) {
		tiling.set({ ...EMPTY });
		return;
	}
	const area = workArea();
	const nc = t.cols.length;
	t.cells.forEach((id, idx) => {
		if (!id || !list.some((w) => w.id === id)) return;
		const rect = cellRect(t.cols, t.rows, idx % nc, Math.floor(idx / nc), area);
		setGeometry(id, {
			...rect,
			max: false,
			min: false,
			snappedCell: `tile-${idx % nc}-${Math.floor(idx / nc)}`
		});
	});
}

/** Tile the front-most (highest-z, non-minimized) windows into `mode`'s grid.
 *  Needs ≥2 open windows; fills cells row-major, leaving trailing cells empty
 *  when there are fewer windows than cells. */
export function applyTiling(mode: TileMode): boolean {
	const d = DEFAULTS[mode];
	const need = d.cols.length * d.rows.length;
	const open = get(windows)
		.filter((w) => !w.min)
		.sort((a, b) => b.z - a.z);
	if (open.length < 2) return false;
	const cells: string[] = [];
	for (let i = 0; i < need; i++) cells.push(open[i]?.id ?? '');
	tiling.set({ mode, cols: [...d.cols], rows: [...d.rows], cells });
	retile();
	return true;
}

/** Drag handler for a vertical gutter: boundary `i` → x fraction. */
export function setColumnBoundary(i: number, frac: number): void {
	tiling.update((t) => ({ ...t, cols: moveBoundary(t.cols, i, frac) }));
	retile();
}

/** Drag handler for a horizontal gutter: boundary `i` → y fraction. */
export function setRowBoundary(i: number, frac: number): void {
	tiling.update((t) => ({ ...t, rows: moveBoundary(t.rows, i, frac) }));
	retile();
}

/** Leave tiling (windows keep their current geometry). */
export function clearTiling(): void {
	tiling.set({ ...EMPTY });
}
