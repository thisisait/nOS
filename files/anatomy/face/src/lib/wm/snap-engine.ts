/**
 * WM v2 · SnapEngine — pure layout math (Wave-1 G3).
 *
 * Turns an active `LayoutSpec` (cells in [0..1] fractions of the work area) into
 * pixel rects, and resolves a `cellId` → the geometry a window takes when snapped
 * into it. Registered with the frozen desktop store via `useSnapEngine()` (see
 * `init.ts`); `snapWindow(id, layout, cellId, area)` then applies `rectFor(...)`.
 *
 * These are PURE functions with no Svelte / DOM dependency so they unit-test in
 * plain node (see `snap-engine.test.ts`).
 */
import type { SnapEngine } from '$lib/stores/desktop';
import type { LayoutSpec } from '$lib/contracts';

export type PixelRect = { x: number; y: number; w: number; h: number };
export type PixelCell = { id: string } & PixelRect;
export type Area = { w: number; h: number };

/** Fraction (clamped to [0..1]) → integer pixels against a length. */
function px(fraction: number, length: number): number {
	const f = Math.min(1, Math.max(0, fraction));
	return Math.round(f * length);
}

/** Resolve one cell spec into a pixel rect. Right/bottom edges are computed from
 *  the far edge so adjacent cells tile flush (no 1px seams from double-rounding). */
function cellRect(cell: { x: number; y: number; w: number; h: number }, area: Area): PixelRect {
	const x = px(cell.x, area.w);
	const y = px(cell.y, area.h);
	const right = px(cell.x + cell.w, area.w);
	const bottom = px(cell.y + cell.h, area.h);
	return { x, y, w: Math.max(0, right - x), h: Math.max(0, bottom - y) };
}

/**
 * The concrete SnapEngine registered with the desktop store.
 * `area` is the desktop WORK area in CSS px (viewport minus the menubar) — the
 * integrator supplies it; cells are laid out relative to that origin.
 */
export const snapEngine: SnapEngine = {
	cells(layout: LayoutSpec, area: Area): PixelCell[] {
		return layout.cells.map((c) => ({ id: c.id, ...cellRect(c, area) }));
	},
	rectFor(layout: LayoutSpec, cellId: string, area: Area): PixelRect | null {
		const c = layout.cells.find((x) => x.id === cellId);
		return c ? cellRect(c, area) : null;
	}
};

/** Point-in-cell hit test (drop resolution). Returns the id of the first pixel
 *  cell that contains `(px,py)`, or null. `cellsFor` rects are area-relative, so
 *  the caller passes an area-relative point (subtract the work-area origin). */
export function cellAt(cells: PixelCell[], point: { x: number; y: number }): string | null {
	for (const c of cells) {
		if (point.x >= c.x && point.x < c.x + c.w && point.y >= c.y && point.y < c.y + c.h) {
			return c.id;
		}
	}
	return null;
}
