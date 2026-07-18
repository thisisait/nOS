/**
 * Desktop store — the shared window/z-order state and the FROZEN extension
 * seam (Wave 0). Wave-1 groups attach behavior via `useSnapEngine` (G3) and
 * `usePersistence` (G4) instead of editing the mutators, so their worktrees
 * never touch the same lines.
 *
 * Pure `svelte/store` (not runes) so it is unit-testable in plain node/vitest.
 */
import { writable, get, type Writable } from 'svelte/store';
import type { WindowModel, WindowGeometry, LayoutSpec } from '$lib/contracts';

// ── Extension interfaces (implemented by Wave-1 groups) ──────────────────────

/** G3 (snap/tiling) implements this to turn the active layout into pixel cells
 *  and to resolve a drop point → a cell id. */
export interface SnapEngine {
	/** Pixel rects for the active layout's cells, given the work-area size. */
	cells(
		layout: LayoutSpec,
		area: { w: number; h: number }
	): Array<{
		id: string;
		x: number;
		y: number;
		w: number;
		h: number;
	}>;
	/** The geometry a window takes when snapped into `cellId`. */
	rectFor(
		layout: LayoutSpec,
		cellId: string,
		area: { w: number; h: number }
	): { x: number; y: number; w: number; h: number } | null;
}

/** G4 (per-viewport cache) implements this to persist/restore geometry. The
 *  adapter owns its own debounce (30 s) — the store just notifies it. */
export interface PersistenceAdapter {
	/** Called after any geometry-changing mutation. */
	onChange(windows: WindowModel[]): void;
	/** Restore saved geometry for the current viewport bucket, if any. */
	restore(): Promise<WindowGeometry[] | null>;
}

// ── State ─────────────────────────────────────────────────────────────────────

export const windows: Writable<WindowModel[]> = writable([]);
export const activeLayoutSlug: Writable<string> = writable('single');

let snapEngine: SnapEngine | null = null;
let persistence: PersistenceAdapter | null = null;
let zTop = 10;

export function useSnapEngine(engine: SnapEngine): void {
	snapEngine = engine;
}
export function usePersistence(adapter: PersistenceAdapter): void {
	persistence = adapter;
}
export function getSnapEngine(): SnapEngine | null {
	return snapEngine;
}

function notify(): void {
	persistence?.onChange(get(windows));
}

// ── Mutators ──────────────────────────────────────────────────────────────────

let counter = 0;
export function nextId(app: string): string {
	counter += 1;
	return `${app}-${counter}`;
}

export function openWindow(w: Partial<WindowModel> & { app: string; title: string }): string {
	const id = w.id ?? nextId(w.app);
	zTop += 1;
	const model: WindowModel = {
		id,
		app: w.app,
		title: w.title,
		x: w.x ?? 80 + ((counter * 24) % 200),
		y: w.y ?? 80 + ((counter * 24) % 160),
		w: w.w ?? 640,
		h: w.h ?? 440,
		z: zTop,
		min: w.min ?? false,
		max: w.max ?? false,
		snappedCell: w.snappedCell
	};
	windows.update((list) => [...list, model]);
	notify();
	return id;
}

export function closeWindow(id: string): void {
	windows.update((list) => list.filter((w) => w.id !== id));
	notify();
}

export function focusWindow(id: string): void {
	zTop += 1;
	windows.update((list) => list.map((w) => (w.id === id ? { ...w, z: zTop, min: false } : w)));
	// focus is not geometry — no persist needed, but z-order restore is nice-to-have
	notify();
}

export function moveWindow(id: string, x: number, y: number): void {
	windows.update((list) =>
		list.map((w) => (w.id === id ? { ...w, x, y, snappedCell: undefined } : w))
	);
	notify();
}

export function resizeWindow(id: string, w: number, h: number): void {
	windows.update((list) =>
		list.map((win) => (win.id === id ? { ...win, w, h, snappedCell: undefined } : win))
	);
	notify();
}

export function setGeometry(id: string, g: Partial<WindowModel>): void {
	windows.update((list) => list.map((w) => (w.id === id ? { ...w, ...g } : w)));
	notify();
}

export function toggleMin(id: string): void {
	windows.update((list) => list.map((w) => (w.id === id ? { ...w, min: !w.min } : w)));
	notify();
}

export function toggleMax(id: string): void {
	windows.update((list) => list.map((w) => (w.id === id ? { ...w, max: !w.max } : w)));
	notify();
}

/** Snap a window into a layout cell (tiled mode). G3 supplies the SnapEngine +
 *  the LayoutSpec; the store just applies the resolved rect. */
export function snapWindow(
	id: string,
	layout: LayoutSpec,
	cellId: string,
	area: { w: number; h: number }
): void {
	if (!snapEngine) return;
	const rect = snapEngine.rectFor(layout, cellId, area);
	if (!rect) return;
	windows.update((list) =>
		list.map((w) => (w.id === id ? { ...w, ...rect, max: false, snappedCell: cellId } : w))
	);
	notify();
}

/** Restore geometry for the current viewport bucket via the persistence adapter,
 *  merging saved rects into any already-open windows (cascade for unseen ones). */
export async function restoreGeometry(): Promise<void> {
	if (!persistence) return;
	const saved = await persistence.restore();
	if (!saved || saved.length === 0) return;
	const byId = new Map(saved.map((g) => [g.id, g]));
	windows.update((list) =>
		list.map((w) => {
			const g = byId.get(w.id);
			return g
				? { ...w, x: g.x, y: g.y, w: g.w, h: g.h, z: g.z, min: g.min, snappedCell: g.snappedCell }
				: w;
		})
	);
}

/** Test/reset hook. */
export function _reset(): void {
	windows.set([]);
	activeLayoutSlug.set('single');
	snapEngine = null;
	persistence = null;
	zTop = 10;
	counter = 0;
}
