// The person's workspaces: tabs of widgets on a 12-column grid and a floating chat
// (files/anatomy/contracts/workspace-layout.yml). Pure reducers; the Rust bridge checks
// and stores the layout, the model never sees it.
import type { DashboardProps, Lens, ToShell, ToThalamus, WidgetSpec } from './wire';
import { onTableChanged as staleOrSend, type WidgetState, type Widgets } from './widgets';

export type Grid = { x: number; y: number; w: number; h: number };
export type WidgetBox = Grid & { id: string; title: string; spec: WidgetSpec };
/** `lens`: the tab's shared filter (a placed dashboard's); it joins a widget's where only when it is sent. */
export type Space = { id: string; name: string; lens?: Lens[]; widgets: WidgetBox[] };
export type Chat = { x: number; y: number; w: number; h: number; open: boolean };
export type Layout = { version: 2; active: string; chat: Chat; workspaces: Space[] };
type Send = ToThalamus[];

export const COLS = 12;
export const ROW_PX = 40;
export const MAX_SPACES = 12;
export const MAX_WIDGETS = 24;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export const empty = (): Layout => ({
	version: 2, active: 'ws1', chat: { x: 0, y: 0, w: 0, h: 0, open: true },
	workspaces: [{ id: 'ws1', name: 'Workspace', widgets: [] }]
});

/** Integer units inside the grid: w 2..12, h 2..40, x + w <= 12, y 0..400. */
export function place(g: Grid): Grid {
	const w = clamp(Math.round(g.w), 2, COLS);
	return { x: clamp(Math.round(g.x), 0, COLS - w), y: clamp(Math.round(g.y), 0, 400), w, h: clamp(Math.round(g.h), 2, 40) };
}

/** A drag from `start` by (dx, dy) px; resize grows to the right edge, never past it. */
export function byPointer(start: Grid, mode: 'move' | 'resize', dx: number, dy: number, colPx: number, rowPx: number): Grid {
	const du = Math.round(dx / colPx), dv = Math.round(dy / rowPx);
	if (mode === 'move') return place({ ...start, x: start.x + du, y: start.y + dv });
	return place({ ...start, w: clamp(start.w + du, 2, COLS - start.x), h: start.h + dv });
}

const ARROWS: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

/** Arrows move a focused handle one unit, shift+arrows resize; null for any other key. */
export function byKey(g: Grid, key: string, shift: boolean): Grid | null {
	const d = ARROWS[key];
	if (!d) return null;
	return shift ? place({ ...g, w: clamp(g.w + d[0], 2, COLS - g.x), h: g.h + d[1] }) : place({ ...g, x: g.x + d[0], y: g.y + d[1] });
}

const activeSpace = (l: Layout) => l.workspaces.find((s) => s.id === l.active) ?? l.workspaces[0];

/** The lens on a spec as it is sent: each set condition joins a rows or chart where, after its own; a form is untouched. */
export function lensed(spec: WidgetSpec, lens: Lens[] = []): WidgetSpec {
	const add = lens.filter((c) => c.value !== '').map(({ column, op, value }) => ({ column, op, value }));
	if (!add.length || 'form' in spec) return spec;
	if ('rows' in spec) return { rows: { ...spec.rows, where: [...(Array.isArray(spec.rows.where) ? spec.rows.where : []), ...add] } };
	return { chart: { ...spec.chart, query: { ...spec.chart.query, where: [...(spec.chart.query.where ?? []), ...add] } } };
}

const mapWidgets = (l: Layout, f: (w: WidgetBox[]) => WidgetBox[]): Layout => ({
	...l, workspaces: l.workspaces.map((s) => ({ ...s, widgets: f(s.widgets) }))
});

export function setBox(l: Layout, id: string, g: Grid): Layout {
	return mapWidgets(l, (ws) => ws.map((w) => (w.id === id ? { ...w, ...place(g) } : w)));
}

// ponytail: no collision check; boxes may overlap like windows, add packing if people ask.
/** A new widget on the active tab, below the others; it runs once, as a click. */
export function addWidget(l: Layout, id: string, title: string, spec: WidgetSpec): { layout: Layout; send: ToThalamus | null } {
	const here = activeSpace(l);
	if (here.widgets.length >= MAX_WIDGETS) return { layout: l, send: null };
	const y = Math.max(0, ...here.widgets.map((w) => w.y + w.h));
	const box: WidgetBox = { id, title: title.slice(0, 120), spec, ...place({ x: 0, y, w: 6, h: 8 }) };
	return {
		layout: { ...l, workspaces: l.workspaces.map((s) => (s === here ? { ...s, widgets: [...s.widgets, box] } : s)) },
		send: { t: 'widget', widget: id, spec: lensed(spec, here.lens), trigger: 'click' }
	};
}

/** addWidget, and the widget's state: its spec, not run yet. */
export function placed(l: Layout, w: Widgets, id: string, title: string, spec: WidgetSpec): { layout: Layout; w: Widgets; send: ToThalamus | null } {
	const r = addWidget(l, id, title, spec);
	if (!r.send) return { layout: l, w, send: null };
	return { layout: r.layout, w: { ...w, [id]: { component: null, error: null, at: 0, spec } }, send: r.send };
}

/** The person's click on a render's pin: a widget of a copy of that spec, titled as the render. Nothing for no pin. */
export function pin(l: Layout, w: Widgets, id: string, m: ToShell): { layout: Layout; w: Widgets; send: ToThalamus | null } {
	if (m.t !== 'render' || !m.pin) return { layout: l, w, send: null };
	const p = m.component.props as { title?: string; name?: string };
	// msg lives in $state: a Proxy, which structuredClone refuses. JSON is all a spec is.
	const spec = JSON.parse(JSON.stringify(m.pin)) as WidgetSpec;
	const table = 'rows' in spec ? String(spec.rows.table ?? '') : 'chart' in spec ? spec.chart.query.table : spec.form.table;
	return placed(l, w, id, p.title || p.name || table, spec);
}

export const removeWidget = (l: Layout, id: string): Layout => mapWidgets(l, (ws) => ws.filter((w) => w.id !== id));

export function addSpace(l: Layout, id: string, name: string): Layout {
	if (l.workspaces.length >= MAX_SPACES) return l;
	return { ...l, active: id, workspaces: [...l.workspaces, { id, name: name.slice(0, 40), widgets: [] }] };
}

export function removeSpace(l: Layout, id: string): Layout {
	const rest = l.workspaces.filter((s) => s.id !== id);
	if (!rest.length) return l;
	return { ...l, workspaces: rest, active: l.active === id ? rest[0].id : l.active };
}

const run = (w: WidgetState): 'restore' | 'table_changed' => (w.stale ? 'table_changed' : 'restore');

/** The widgets on `tab` that are stale or never ran, sent now; the others wait for their tab. */
function due(l: Layout, w: Widgets): { w: Widgets; send: Send } {
	const out = { ...w };
	const send: Send = [];
	const here = activeSpace(l);
	for (const box of here.widgets) {
		const s = out[box.id];
		if (!s || !(s.stale || s.due)) continue;
		send.push({ t: 'widget', widget: box.id, spec: lensed(box.spec, here.lens), trigger: run(s) });
		out[box.id] = { ...s, stale: false, due: false };
	}
	return { w: out, send };
}

/** A saved layout came back: every widget remembers its spec, only the active tab runs. */
export function restore(l: Layout): { w: Widgets; send: Send } {
	const w: Widgets = {};
	for (const s of l.workspaces) for (const box of s.widgets) w[box.id] = { component: null, error: null, at: 0, spec: box.spec, due: true };
	return due(l, w);
}

/** Show `tab`; its stale or never-run widgets run now. */
export function show(l: Layout, w: Widgets, tab: string): { layout: Layout; w: Widgets; send: Send } {
	if (!l.workspaces.some((s) => s.id === tab)) return { layout: l, w, send: [] };
	const layout = { ...l, active: tab };
	return { layout, ...due(layout, w) };
}

/** A write landed in `table`: the active tab's readers re-run, the rest go stale. */
export function onTableChanged(l: Layout, w: Widgets, table: string): { w: Widgets; send: Send } {
	const here = activeSpace(l);
	const r = staleOrSend(w, table, here.widgets.map((b) => b.id));
	return { w: r.w, send: r.send.map((m) => (m.t === 'widget' ? { ...m, spec: lensed(m.spec, here.lens) } : m)) };
}

/** The person set lens condition `i` of `tab`: every widget there re-runs, as a click. */
export function setLens(l: Layout, tab: string, i: number, value: string): { layout: Layout; send: Send } {
	const s = l.workspaces.find((x) => x.id === tab);
	if (!s?.lens?.[i]) return { layout: l, send: [] };
	const lens = s.lens.map((c, j) => (j === i ? { ...c, value: value.slice(0, 120) } : c));
	return {
		layout: { ...l, workspaces: l.workspaces.map((x) => (x === s ? { ...s, lens } : x)) },
		send: s.widgets.map((b) => ({ t: 'widget', widget: b.id, spec: lensed(b.spec, lens), trigger: 'click' }))
	};
}

/** The person's click on "Place on a new tab": a tab with the offer's lens, two widgets a row; each runs once, as a click. */
export function placeOffer(l: Layout, w: Widgets, tab: string, d: DashboardProps, id: () => string): { layout: Layout; w: Widgets; send: Send } {
	if (l.workspaces.length >= MAX_SPACES) return { layout: l, w, send: [] };
	// The offer lives in $state: a Proxy. JSON is all an offer is.
	const { name, lens, widgets } = JSON.parse(JSON.stringify(d)) as DashboardProps;
	const boxes: WidgetBox[] = widgets.slice(0, MAX_WIDGETS).map((x, i) => ({ id: id(), title: x.title.slice(0, 120), spec: x.spec, ...place({ x: (i % 2) * 6, y: Math.floor(i / 2) * 8, w: 6, h: 8 }) }));
	const out = { ...w };
	for (const b of boxes) out[b.id] = { component: null, error: null, at: 0, spec: b.spec };
	return {
		layout: { ...l, active: tab, workspaces: [...l.workspaces, { id: tab, name: name.slice(0, 40), lens, widgets: boxes }] },
		w: out,
		send: boxes.map((b) => ({ t: 'widget', widget: b.id, spec: lensed(b.spec, lens), trigger: 'click' }))
	};
}

/** An approval waits: the chat opens on top, since its card lives there. */
export const approvalArrived = (l: Layout): { layout: Layout; top: 'chat' } => ({ layout: { ...l, chat: { ...l.chat, open: true } }, top: 'chat' });

/** The chat inside the viewport, at least 280×240; a fresh one (w 0) docks top right. */
export function clampChat(c: Chat, vp: { w: number; h: number }): Chat {
	const fresh = c.w === 0 || c.h === 0;
	const w = clamp(fresh ? 380 : c.w, Math.min(280, vp.w), vp.w);
	const h = clamp(fresh ? Math.min(560, vp.h - 32) : c.h, Math.min(240, vp.h), vp.h);
	const x = fresh ? vp.w - w - 16 : c.x, y = fresh ? 16 : c.y;
	return { x: clamp(x, 0, vp.w - w), y: clamp(y, 0, vp.h - h), w, h, open: c.open };
}

/** How old a widget's answer is, by the pupil's own clock. */
export function age(s: WidgetState | undefined, now: number): string {
	if (s?.stale) return 'stale: the table changed';
	if (!s || s.at === 0) return 'not run yet';
	const sec = Math.max(0, Math.round((now - s.at) / 1000));
	return sec < 60 ? `${sec} s ago` : sec < 3600 ? `${Math.round(sec / 60)} min ago` : `${Math.round(sec / 3600)} h ago`;
}
