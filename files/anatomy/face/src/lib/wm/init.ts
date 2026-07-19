/**
 * WM v2 · bootstrap (Wave-1 G3).
 *
 * `initWindowManager()` registers the SnapEngine with the frozen desktop store
 * (via `useSnapEngine`) and loads the tiling layouts from `face-layouts` (falling
 * back to the built-in set). The integrator calls this ONCE at desktop mount
 * (see +page.svelte INTEGRATION NOTE), before/around mounting <SnapOverlay />.
 */
import { useSnapEngine } from '$lib/stores/desktop';
import { snapEngine } from './snap-engine';
import { loadLayouts } from './layouts';
import type { LayoutSpec } from '$lib/contracts';

let registered = false;

/**
 * Register the SnapEngine and load layouts. Safe to call more than once — the
 * engine is only registered the first time; layouts re-load each call (cheap,
 * and lets the caller refresh after KEAP comes up). Resolves with the layout set.
 */
export async function initWindowManager(): Promise<LayoutSpec[]> {
	if (!registered) {
		useSnapEngine(snapEngine);
		registered = true;
	}
	return loadLayouts();
}

/** Test hook: forget the registration flag so a later init re-registers. */
export function _resetWindowManager(): void {
	registered = false;
}
