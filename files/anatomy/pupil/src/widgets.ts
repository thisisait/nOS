// Each widget's latest answer by the pupil's own token (wire.rs ToShell::Widget). A widget's
// answer never joins the chat log; a refusal that names a widget is shown on that widget.
import type { Component, ToShell } from './wire';

export type WidgetState = { component: Component | null; error: string | null; at: number };
export type Widgets = Record<string, WidgetState>;

/** The new state when `m` is a widget's; null when it is the log's. */
export function route(w: Widgets, m: ToShell, now: number): Widgets | null {
	if (m.t === 'widget') return { ...w, [m.widget]: { component: m.component, error: null, at: now } };
	if (m.t === 'refused' && m.widget)
		return { ...w, [m.widget]: { component: w[m.widget]?.component ?? null, error: m.reason, at: now } };
	return null;
}
