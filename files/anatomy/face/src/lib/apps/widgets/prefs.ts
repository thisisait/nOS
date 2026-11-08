/** Per-viewer widget prefs (row face-widgets-movable-removable): which widgets are hidden and
 *  where a moved one sits. Stored in user-state `face.widgets`, like window geometry. */
import { writable, get } from 'svelte/store';
import { usGet, usSet } from '$lib/api/userstate';

export const WIDGETS_NS = 'face.widgets';
export type WidgetPrefs = { hidden: string[]; pos: Record<string, { x: number; y: number }> };

/** The Anatomy widget starts hidden (operator 2026-11-08: useless on the desktop as it was). */
export const DEFAULT_PREFS: WidgetPrefs = { hidden: ['anatomy-widget'], pos: {} };

export const widgetPrefs = writable<WidgetPrefs>(DEFAULT_PREFS);

export async function loadWidgetPrefs(): Promise<void> {
	try {
		const v = await usGet<WidgetPrefs>(WIDGETS_NS, 'prefs');
		if (v && Array.isArray(v.hidden) && v.pos && typeof v.pos === 'object') widgetPrefs.set(v);
	} catch {
		// user-state unreachable: keep the defaults, never block the desktop
	}
}

function save(next: WidgetPrefs): void {
	widgetPrefs.set(next);
	usSet(WIDGETS_NS, 'prefs', next).catch(() => {});
}

export function setWidgetHidden(slug: string, hidden: boolean): void {
	const p = get(widgetPrefs);
	const rest = p.hidden.filter((s) => s !== slug);
	save({ ...p, hidden: hidden ? [...rest, slug] : rest });
}

/** Clamp into the viewport so a widget can never be dragged out of reach. */
export function moveWidget(slug: string, x: number, y: number, w = 1e6, h = 1e6): void {
	const p = get(widgetPrefs);
	const pos = {
		x: Math.max(0, Math.min(Math.round(x), w - 40)),
		y: Math.max(0, Math.min(Math.round(y), h - 40))
	};
	save({ ...p, pos: { ...p.pos, [slug]: pos } });
}
