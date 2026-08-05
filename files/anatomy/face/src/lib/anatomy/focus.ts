/**
 * Cross-window request: "open Anatomy on THIS view".
 *
 * The menubar and the Anatomy window are not in a parent/child relationship —
 * the bar lives at the desktop root, the app lives inside a window the window
 * manager owns — so a prop cannot connect them. A tiny store can.
 *
 * It carries a REQUEST, not state. The app consumes it and clears it, so a
 * second click on the same chip fires again rather than being swallowed as "no
 * change" — which is the bug every naive `selectedView` store has.
 */
import { writable } from 'svelte/store';

export type AnatomyView = 'pulse' | 'wing' | 'bone';

export interface AnatomyFocus {
	view: AnatomyView;
	/** An actor_action_id to narrow the Wing view to, when following a run. */
	thread?: string;
	/** Distinguishes two identical requests. Without it, clicking the same chip
	 *  twice is one store value and the second click does nothing. */
	nonce: number;
}

export const anatomyFocus = writable<AnatomyFocus | null>(null);

let seq = 0;

/** Ask the Anatomy app to show `view`. Safe to call when it is not open — the
 *  caller launches the window, and the app reads this on mount. */
export function requestAnatomy(view: AnatomyView, thread?: string): void {
	anatomyFocus.set({ view, thread, nonce: ++seq });
}
