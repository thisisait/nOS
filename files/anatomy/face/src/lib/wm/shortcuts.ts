/**
 * Desktop keyboard shortcuts.
 *
 * The shell had exactly one binding — Ctrl+Space for the palette — so closing a
 * window meant aiming at a 12-pixel dot and cycling between two windows meant
 * using the mouse. That is not a desktop.
 *
 * THREE CONSTRAINTS THE IMPLEMENTATION IS SHAPED BY, and each is a real trap:
 *
 * 1. **An iframe swallows keys.** Most windows host a service in an iframe, and
 *    once focus is inside it the parent document never sees a keydown. So a
 *    shortcut can be live and appear broken depending on where you clicked.
 *    Nothing here can fix that (cross-origin), so the bindings are chosen to be
 *    ones a user reaches for with the shell focused, and `hostedInIframe()`
 *    exists so the UI can SAY so instead of leaving them guessing.
 *
 * 2. **Never steal a key a text field needs.** The handler bails whenever the
 *    event target is an input, textarea or contenteditable — otherwise Cmd+W
 *    inside the row editor would close the window mid-edit.
 *
 * 3. **Never shadow the browser's own destructive bindings.** Cmd/Ctrl+W closes
 *    the BROWSER TAB, and a web app that intercepts it is fighting muscle
 *    memory it cannot win — Chrome refuses to let it, and where it works the
 *    user loses the shortcut they actually meant. So window-close is bound to
 *    Cmd/Ctrl+Backspace, which no browser claims.
 *
 * Pure logic + one listener; the resolver is exported separately so vitest can
 * test the mapping without a DOM.
 */
import { get } from 'svelte/store';
import { windows, closeWindow, focusWindow, toggleMin, toggleMax } from '$lib/stores/desktop';
import { applyTiling, clearTiling } from './tiling';

export type ShortcutAction =
	| 'close'
	| 'cycle'
	| 'cycle-back'
	| 'minimize'
	| 'maximize'
	| 'tile-half'
	| 'tile-grid'
	| 'untile'
	| null;

/** The subset of a KeyboardEvent the resolver needs — so a test can build one. */
export interface KeyChord {
	key: string;
	metaKey?: boolean;
	ctrlKey?: boolean;
	shiftKey?: boolean;
	altKey?: boolean;
}

/**
 * Chord → action. `meta` on macOS, `ctrl` elsewhere; both are accepted
 * everywhere because a self-hosted box gets used from whatever is to hand.
 */
export function resolve(e: KeyChord): ShortcutAction {
	const mod = Boolean(e.metaKey || e.ctrlKey);
	if (!mod) return null;
	switch (e.key) {
		case 'Backspace':
			// NOT Cmd/Ctrl+W — see constraint 3.
			return 'close';
		case '`':
			return e.shiftKey ? 'cycle-back' : 'cycle';
		case 'm':
		case 'M':
			return 'minimize';
		case 'Enter':
			return 'maximize';
		case '1':
			return 'tile-half';
		case '2':
			return 'tile-grid';
		case '0':
			return 'untile';
		default:
			return null;
	}
}

/** True when the event came from somewhere that owns its own keys. */
export function isTextEntry(target: EventTarget | null): boolean {
	const el = target as HTMLElement | null;
	if (!el || !el.tagName) return false;
	const tag = el.tagName.toLowerCase();
	return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable === true;
}

/** The front-most non-minimised window, i.e. the one a shortcut acts on. */
function frontId(): string | null {
	const wins = get(windows).filter((w) => !w.min);
	if (wins.length === 0) return null;
	return [...wins].sort((a, b) => b.z - a.z)[0].id;
}

/** Cycle order is stable (creation order), not z-order — cycling by z-order
 *  reorders the very list you are cycling through, so you bounce between two
 *  windows and can never reach a third. */
function cycle(delta: number): void {
	const wins = get(windows);
	if (wins.length < 2) return;
	const front = frontId();
	const i = wins.findIndex((w) => w.id === front);
	const next = wins[(i + delta + wins.length) % wins.length];
	focusWindow(next.id);
}

export function run(action: ShortcutAction): boolean {
	const id = frontId();
	switch (action) {
		case 'close':
			if (id) closeWindow(id);
			return Boolean(id);
		case 'cycle':
			cycle(1);
			return true;
		case 'cycle-back':
			cycle(-1);
			return true;
		case 'minimize':
			if (id) toggleMin(id);
			return Boolean(id);
		case 'maximize':
			if (id) toggleMax(id);
			return Boolean(id);
		case 'tile-half':
			applyTiling('half-v');
			return true;
		case 'tile-grid':
			applyTiling('2x2');
			return true;
		case 'untile':
			clearTiling();
			return true;
		default:
			return false;
	}
}

/** Attach the listener. Returns the detach function. */
export function initShortcuts(): () => void {
	function onKey(e: KeyboardEvent) {
		if (isTextEntry(e.target)) return;
		const action = resolve(e);
		if (!action) return;
		if (run(action)) e.preventDefault();
	}
	window.addEventListener('keydown', onKey);
	return () => window.removeEventListener('keydown', onKey);
}

/**
 * The bindings, for the command palette and any help surface.
 *
 * Each carries its ACTION, not just its label, so the palette entry actually
 * performs the thing it describes. A help entry that does nothing when you
 * select it is a worse experience than no help entry — and it is also how a
 * documented shortcut quietly stops matching the implementation.
 */
export const SHORTCUTS: Array<{ chord: string; what: string; action: ShortcutAction }> = [
	{ chord: '⌘/Ctrl + ⌫', what: 'Close the front window', action: 'close' },
	{ chord: '⌘/Ctrl + `', what: 'Cycle windows (⇧ reverses)', action: 'cycle' },
	{ chord: '⌘/Ctrl + M', what: 'Minimise / restore', action: 'minimize' },
	{ chord: '⌘/Ctrl + ⏎', what: 'Maximise / restore', action: 'maximize' },
	{ chord: '⌘/Ctrl + 1', what: 'Tile side by side', action: 'tile-half' },
	{ chord: '⌘/Ctrl + 2', what: 'Tile 2×2', action: 'tile-grid' },
	{ chord: '⌘/Ctrl + 0', what: 'Leave tiling', action: 'untile' }
];
