/**
 * Layout mode — the ONE place a viewport turns into a shell decision.
 *
 * The breakpoint is DATA, not a number retyped in every stylesheet:
 * `BREAKPOINTS` is the only declaration, `MEDIA` derives the matchMedia
 * strings from it, and `resolveMode` is the only rule. A component that wants
 * to know "are we on a phone" reads the `layoutMode` store — it does not
 * measure anything itself.
 *
 * Pointer capability is part of the decision, not a refinement of it. A
 * 1280px tablet has the width for floating windows and none of the precision:
 * a 16px resize grip and a hover-only window switcher are mouse affordances.
 * So a coarse pointer never resolves to `desktop`.
 *
 * What each mode means for the shell:
 *   desktop — windows, drag, resize, tiling, dock, widgets, hover switcher.
 *   tablet  — the same, unchanged; the mode exists so a surface can grow
 *             touch-sized targets without pretending to be a phone.
 *   mobile  — NO windows. One full-screen app at a time plus a switcher
 *             (see MobileShell). Dragging a window and overlapping two of
 *             them do not work with a thumb on 390px, so mobile does not
 *             offer them rather than offering them broken.
 *
 * Pure module: no DOM at import time, unit-testable in node.
 */
import { writable } from 'svelte/store';
import type { WindowModel } from '$lib/contracts';

/** Upper bound (exclusive) of each mode's width band, in CSS px. */
export const BREAKPOINTS = { mobile: 720, tablet: 1080 } as const;

export type LayoutMode = 'mobile' | 'tablet' | 'desktop';

export interface Viewport {
	width: number;
	/** `(pointer: coarse)` — touch/pen as the PRIMARY input. */
	coarsePointer?: boolean;
}

export function resolveMode({ width, coarsePointer = false }: Viewport): LayoutMode {
	if (width < BREAKPOINTS.mobile) return 'mobile';
	if (coarsePointer || width < BREAKPOINTS.tablet) return 'tablet';
	return 'desktop';
}

/** Whether this mode has a window manager at all. */
export function usesWindows(mode: LayoutMode): boolean {
	return mode !== 'mobile';
}

/** The media queries, derived — never hand-written beside a breakpoint. */
export const MEDIA = {
	mobile: `(max-width: ${BREAKPOINTS.mobile - 0.02}px)`,
	tablet: `(max-width: ${BREAKPOINTS.tablet - 0.02}px)`,
	coarse: '(pointer: coarse)'
} as const;

/**
 * How mobile stacks apps: exactly one surface is on screen, and it is the
 * front-most window the window store already tracks. Mobile therefore adds no
 * second notion of "current app" — z-order IS the stack, which is why a
 * launch, a dock tap and a restore all land on the right surface for free.
 * A minimised window is not on screen, so it is not a candidate.
 */
export function frontWindow(list: readonly WindowModel[]): WindowModel | null {
	let front: WindowModel | null = null;
	for (const w of list) if (!w.min && (front === null || w.z > front.z)) front = w;
	return front;
}

/** The live mode. `desktop` until `initLayoutMode()` measures (SSR-safe). */
export const layoutMode = writable<LayoutMode>('desktop');

/**
 * Start tracking the mode. matchMedia, not a resize listener: the browser
 * already knows when a band boundary is crossed, and a resize handler would
 * recompute on every pixel to learn the same thing.
 */
export function initLayoutMode(): () => void {
	if (typeof window === 'undefined' || !window.matchMedia) return () => {};
	const qs = [MEDIA.mobile, MEDIA.tablet, MEDIA.coarse].map((q) => window.matchMedia(q));
	const read = () =>
		layoutMode.set(resolveMode({ width: window.innerWidth, coarsePointer: qs[2].matches }));
	read();
	for (const q of qs) q.addEventListener('change', read);
	return () => {
		for (const q of qs) q.removeEventListener('change', read);
	};
}
