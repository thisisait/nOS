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

export type AnatomyView = 'pulse' | 'wing' | 'bone' | 'graph' | 'runs';

export interface AnatomyFocus {
	view: AnatomyView;
	/** An actor_action_id to narrow the Wing view to, when following a run. */
	thread?: string;
	/** A graph node id to select in the Graph view, when arriving from a
	 *  surface that was already pointing at one (the desktop widget). Without
	 *  it a click on a node opens the graph at nothing in particular, and the
	 *  operator has to find again what they had just clicked. */
	node?: string;
	/** Distinguishes two identical requests. Without it, clicking the same chip
	 *  twice is one store value and the second click does nothing. */
	nonce: number;
}

export const anatomyFocus = writable<AnatomyFocus | null>(null);

let seq = 0;

/** Ask the Anatomy app to show `view`. Safe to call when it is not open — the
 *  caller launches the window, and the app reads this on mount. */
export function requestAnatomy(view: AnatomyView, thread?: string, node?: string): void {
	anatomyFocus.set({ view, thread, node, nonce: ++seq });
}
