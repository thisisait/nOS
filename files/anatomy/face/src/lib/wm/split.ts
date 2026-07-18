/**
 * WM v2 · live split (the "multitask" surface).
 *
 * The snap engine tiles into FIXED layout cells (drag-to-top). This adds the
 * missing piece the operator asked for: an explicit two-up split with a
 * draggable gutter in the MIDDLE that re-allocates the ratio between the two
 * tiled windows live. State is session-local (a ratio + the pair of window ids);
 * geometry is applied through the store's `setGeometry` mutator so persistence
 * (G4 per-viewport cache) picks it up like any other move/resize.
 */
import { writable, get } from 'svelte/store';
import { windows, setGeometry } from '$lib/stores/desktop';

/** Desktop menubar height; the work area starts below it. */
export const MENUBAR = 28;

/** Clamp the gutter so neither pane collapses to nothing. */
const MIN_RATIO = 0.15;
const MAX_RATIO = 0.85;

/** Fraction of the work-area width given to the LEFT pane (0..1). */
export const splitRatio = writable(0.5);
/** The two window ids currently tiled left|right, or null when not split. */
export const splitPair = writable<{ left: string; right: string } | null>(null);

function clamp(r: number): number {
	if (!Number.isFinite(r)) return 0.5;
	return Math.min(MAX_RATIO, Math.max(MIN_RATIO, r));
}

function workArea(): { w: number; h: number } {
	const w = typeof window !== 'undefined' ? window.innerWidth : 1280;
	const vh = typeof window !== 'undefined' ? window.innerHeight : 800;
	return { w, h: Math.max(120, vh - MENUBAR) };
}

/** Re-apply left|right geometry for the current pair + ratio. Drops the split
 *  if either window has since closed. */
export function retile(): void {
	const pair = get(splitPair);
	if (!pair) return;
	const list = get(windows);
	const left = list.find((w) => w.id === pair.left);
	const right = list.find((w) => w.id === pair.right);
	if (!left || !right) {
		splitPair.set(null);
		return;
	}
	const { w, h } = workArea();
	const r = clamp(get(splitRatio));
	const lw = Math.round(w * r);
	setGeometry(pair.left, {
		x: 0,
		y: MENUBAR,
		w: lw,
		h,
		max: false,
		min: false,
		snappedCell: 'split-left'
	});
	setGeometry(pair.right, {
		x: lw,
		y: MENUBAR,
		w: w - lw,
		h,
		max: false,
		min: false,
		snappedCell: 'split-right'
	});
}

/** Tile the two front-most (highest-z, non-minimized) windows left|right. The
 *  second-most-recent goes left, the front-most goes right (so the window you
 *  just focused lands under your pointer on the right). */
export function applyHalfSplit(): boolean {
	const open = get(windows)
		.filter((w) => !w.min)
		.sort((a, b) => b.z - a.z);
	if (open.length < 2) return false;
	splitPair.set({ left: open[1].id, right: open[0].id });
	retile();
	return true;
}

/** Set the gutter ratio (from a pointer x / viewport width) and re-tile live. */
export function setSplitRatio(r: number): void {
	splitRatio.set(clamp(r));
	retile();
}

/** Leave split mode (windows keep their current geometry). */
export function clearSplit(): void {
	splitPair.set(null);
}
