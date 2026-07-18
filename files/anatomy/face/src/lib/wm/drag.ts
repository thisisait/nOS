/**
 * WM v2 · drag state seam (Wave-1 G3).
 *
 * The single coordination point between a window's titlebar drag (WM v1, lives in
 * `Window.svelte`) and the snap overlay (`SnapOverlay.svelte`). `Window.svelte`
 * does NOT import the overlay — it only pushes drag state through these three
 * tiny helpers, and the mounted overlay reads the store. This keeps the frozen
 * window chrome untouched apart from 3 one-line calls (see INTEGRATION NOTE).
 *
 * Integrator wiring inside Window.svelte's existing pointer handlers:
 *   import { beginWindowDrag, updateWindowDrag, endWindowDrag } from '$lib/wm/drag';
 *   onTitlePointerDown → after focusWindow(win.id):   beginWindowDrag(win.id, e.clientX, e.clientY);
 *   onPointerMove (dragging branch):                  updateWindowDrag(e.clientX, e.clientY);
 *   onPointerUp:                                      endWindowDrag();
 *
 * The overlay owns the drop→snap decision, so Window.svelte needs no snap logic.
 */
import { writable } from 'svelte/store';

export interface DragState {
	/** True while a window titlebar is being dragged. */
	active: boolean;
	/** The window being dragged (kept after `active` flips false so the overlay
	 *  can resolve the drop on the falling edge). */
	windowId: string | null;
	/** Latest pointer position in viewport (client) CSS px. */
	x: number;
	y: number;
}

const initial: DragState = { active: false, windowId: null, x: 0, y: 0 };

/** The live drag state. `SnapOverlay` subscribes; the window titlebar writes. */
export const dragState = writable<DragState>({ ...initial });

/** Called from the titlebar pointer-down: a window drag has begun. */
export function beginWindowDrag(windowId: string, x: number, y: number): void {
	dragState.set({ active: true, windowId, x, y });
}

/** Called from the titlebar pointer-move: update the live pointer position. */
export function updateWindowDrag(x: number, y: number): void {
	dragState.update((s) => (s.active ? { ...s, x, y } : s));
}

/** Called from the titlebar pointer-up: the drag ended. Flips `active` false but
 *  preserves `windowId`/`x`/`y` so the overlay can commit a snap on this edge. */
export function endWindowDrag(): void {
	dragState.update((s) => ({ ...s, active: false }));
}
