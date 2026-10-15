// Each widget's latest answer by the pupil's own token (wire.rs ToShell::Widget). A widget's
// answer never joins the chat log; a refusal that names a widget is shown on that widget.
import type { Component, ToShell, ToThalamus, Value, WidgetSpec } from './wire';

/** `spec` is what the widget re-runs (workspace.ts); `due`: restored, not run yet; `inFlight` locks a form's submit. */
export type WidgetState = {
	component: Component | null; error: string | null; at: number;
	spec?: WidgetSpec; stale?: boolean; due?: boolean; inFlight?: boolean; added?: string;
};
export type Widgets = Record<string, WidgetState>;

/** The new state when `m` is a widget's; null when it is the log's (table_changed: onTableChanged). */
export function route(w: Widgets, m: ToShell, now: number): Widgets | null {
	if (m.t === 'widget') return { ...w, [m.widget]: { ...w[m.widget], component: m.component, error: null, at: now, stale: false } };
	if (m.t === 'refused' && m.widget)
		return { ...w, [m.widget]: { ...w[m.widget], component: w[m.widget]?.component ?? null, error: m.reason, at: now, inFlight: false } };
	if (m.t === 'form_result')
		return { ...w, [m.widget]: { ...w[m.widget], component: w[m.widget]?.component ?? null, error: null, at: now, inFlight: false, added: m.row } };
	return null;
}

/** The form_submit to send, once: a second submit while one is in flight sends nothing. */
export function submit(w: Widgets, widget: string, m: { form: string; values: Record<string, string | number | boolean> }): { w: Widgets; send: ToThalamus | null } {
	if (w[widget]?.inFlight) return { w, send: null };
	return { w: { ...w, [widget]: { ...w[widget], inFlight: true } }, send: { t: 'form_submit', form: m.form, widget, values: m.values } };
}

export const tableOf = (s: WidgetSpec): string =>
	'rows' in s ? String((s.rows.table as Value) ?? '') : 'chart' in s ? s.chart.query.table : s.form.table;

/** A write landed in `table`: the active widgets that read it re-run, the others go stale. A form never re-runs. */
export function onTableChanged(w: Widgets, table: string, active: readonly string[]): { w: Widgets; send: ToThalamus[] } {
	const out = { ...w };
	const send: ToThalamus[] = [];
	for (const [token, s] of Object.entries(w)) {
		if (!s.spec || 'form' in s.spec || tableOf(s.spec) !== table) continue;
		if (active.includes(token)) send.push({ t: 'widget', widget: token, spec: s.spec, trigger: 'table_changed' });
		else out[token] = { ...s, stale: true };
	}
	return { w: out, send };
}
