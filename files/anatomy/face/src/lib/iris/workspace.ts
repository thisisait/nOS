// The person's workspaces: boards nested by `parent`, each an infinite canvas of widgets, headings,
// frames and boards (cards that open a child) in world pixels, and a floating chat (files/anatomy/contracts/workspace-layout.yml v3). Pure reducers; the
// Rust bridge checks and stores the layout, the model never sees it.
import type { DashboardProps, Lens, ToShell, ToThalamus, WidgetSpec } from './wire';
import { onTableChanged as staleOrSend, tableOf, type WidgetState, type Widgets } from './widgets';

export type Box = { x: number; y: number; w: number; h: number };
export type WidgetItem = Box & { id: string; kind: 'widget'; title: string; spec: WidgetSpec };
export type HeadingItem = Box & { id: string; kind: 'heading'; text: string };
/** A titled rectangle drawn behind the other items. */
export type FrameItem = Box & { id: string; kind: 'frame'; title: string };
/** A card that opens the child workspace `board`. */
export type BoardItem = Box & { id: string; kind: 'board'; board: string };
export type Item = WidgetItem | HeadingItem | FrameItem | BoardItem;
/** Svelte Flow's viewport: the screen px of world 0,0, and the zoom. */
export type View = { x: number; y: number; zoom: number };
/** `lens`: the board's shared filter (a placed dashboard's); it joins a widget's where only when it is sent.
 *  `parent`: the board it opens from (none: a root); `view`: where the canvas was left. */
export type Space = {
	id: string;
	name: string;
	parent?: string;
	lens?: Lens[];
	view?: View;
	items: Item[];
};
export type Chat = { x: number; y: number; w: number; h: number; open: boolean };
export type Layout = { version: 3; active: string; chat: Chat; workspaces: Space[] };
type Send = ToThalamus[];

// 64: as many boards as one board holds cards; a deeper cap is the thalamus's 512 KiB, which workspace.rs checks.
export const MAX_SPACES = 64;
export const MAX_DEPTH = 6;
export const MAX_WIDGETS = 24;
export const MAX_ITEMS = 64;
/** The snap of a drag or an arrow, in world px. */
export const SNAP = 8;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const snap = (v: number) => Math.round(v / SNAP) * SNAP;

export const empty = (): Layout => ({
	version: 3,
	active: 'ws1',
	chat: { x: 0, y: 0, w: 0, h: 0, open: true },
	workspaces: [{ id: 'ws1', name: 'Workspace', items: [] }]
});

/** Integer world px: |x|, |y| <= 100 000, w 80..4000, h 32..4000. */
export function place(g: Box): Box {
	return {
		x: clamp(Math.round(g.x), -100_000, 100_000),
		y: clamp(Math.round(g.y), -100_000, 100_000),
		w: clamp(Math.round(g.w), 80, 4000),
		h: clamp(Math.round(g.h), 32, 4000)
	};
}

/** A drag from `start` by (dx, dy) screen px at `zoom`, snapped to 8 world px. */
export function byPointer(
	start: Box,
	mode: 'move' | 'resize',
	dx: number,
	dy: number,
	zoom: number
): Box {
	const du = snap(dx / zoom),
		dv = snap(dy / zoom);
	if (mode === 'move') return place({ ...start, x: start.x + du, y: start.y + dv });
	return place({ ...start, w: start.w + du, h: start.h + dv });
}

const ARROWS: Record<string, [number, number]> = {
	ArrowLeft: [-1, 0],
	ArrowRight: [1, 0],
	ArrowUp: [0, -1],
	ArrowDown: [0, 1]
};

/** Arrows move a focused item 8 px, shift+arrows resize it; null for any other key. */
export function byKey(g: Box, key: string, shift: boolean): Box | null {
	const d = ARROWS[key];
	if (!d) return null;
	const dx = d[0] * SNAP,
		dy = d[1] * SNAP;
	return shift
		? place({ ...g, w: g.w + dx, h: g.h + dy })
		: place({ ...g, x: g.x + dx, y: g.y + dy });
}

type GridBox = Box & { id: string; title: string; spec: WidgetSpec };
type Old = {
	version: 1 | 2;
	active: string;
	chat: Chat;
	workspaces: { id: string; name: string; lens?: Lens[]; widgets: GridBox[] }[];
};

/** A v1/v2 file's grid units as world px: a column was 100 px on a 1232 px panel, a row 40 px + 8 gap. */
export function migrate(l: Layout | Old): Layout {
	if (l.version === 3) return l;
	return {
		version: 3,
		active: l.active,
		chat: l.chat,
		workspaces: l.workspaces.map(({ widgets, ...s }) => ({
			...s,
			items: widgets.map(({ id, title, spec, x, y, w, h }) => ({
				id,
				kind: 'widget' as const,
				title,
				spec,
				x: x * 100,
				y: y * 48,
				w: w * 100 - 8,
				h: h * 48 - 8
			}))
		}))
	};
}

export const widgetsOf = (s: Space): WidgetItem[] =>
	s.items.filter((i): i is WidgetItem => i.kind === 'widget');
/** The ids from a root down to `id`: workspaces://a/b/c is its path. */
export function chain(l: Layout, id: string): string[] {
	const out: string[] = [];
	for (let at: string | undefined = id; at && out.length < MAX_DEPTH;) {
		out.unshift(at);
		at = l.workspaces.find((s) => s.id === at)?.parent;
	}
	return out;
}
export const pathOf = (l: Layout, id: string) => `workspaces://${chain(l, id).join('/')}`;
const activeSpace = (l: Layout) => l.workspaces.find((s) => s.id === l.active) ?? l.workspaces[0];
const below = (s: Space) => Math.max(0, ...s.items.map((i) => i.y + i.h + SNAP));
const W = 592,
	H = 376; // a v2 widget of 6 x 8 units
/** A world point: the centre of the person's view. */
export type Point = { x: number; y: number };
/** A w x h box centred on `c`, snapped; with no `c`, below the others. */
const spot = (s: Space, w: number, h: number, c?: Point): Box =>
	place(c ? { x: snap(c.x - w / 2), y: snap(c.y - h / 2), w, h } : { x: 0, y: below(s), w, h });

/** The lens on a spec as it is sent: each set condition joins a rows, chart or kpi where, after its own; a form is untouched. */
export function lensed(spec: WidgetSpec, lens: Lens[] = []): WidgetSpec {
	const add = lens
		.filter((c) => c.value !== '')
		.map(({ column, op, value }) => ({ column, op, value }));
	if (!add.length || 'form' in spec) return spec;
	if ('rows' in spec)
		return {
			rows: {
				...spec.rows,
				where: [...(Array.isArray(spec.rows.where) ? spec.rows.where : []), ...add]
			}
		};
	if ('kpi' in spec)
		return {
			kpi: {
				...spec.kpi,
				query: { ...spec.kpi.query, where: [...(spec.kpi.query.where ?? []), ...add] }
			}
		};
	return {
		chart: {
			...spec.chart,
			query: { ...spec.chart.query, where: [...(spec.chart.query.where ?? []), ...add] }
		}
	};
}

const mapItems = (l: Layout, f: (i: Item[]) => Item[]): Layout => ({
	...l,
	workspaces: l.workspaces.map((s) => ({ ...s, items: f(s.items) }))
});

export function setBox(l: Layout, id: string, g: Box): Layout {
	return mapItems(l, (is) => is.map((i) => (i.id === id ? { ...i, ...place(g) } : i)));
}

/** A heading's text or a frame's title, as the person typed it. */
export function setText(l: Layout, id: string, text: string): Layout {
	const t = text.slice(0, 120);
	return mapItems(l, (is) =>
		is.map((i) =>
			i.id !== id
				? i
				: i.kind === 'heading'
					? { ...i, text: t }
					: i.kind === 'frame'
						? { ...i, title: t }
						: i
		)
	);
}

/** Where the person left board `tab`'s canvas; the same view is the same layout. */
export function setView(l: Layout, tab: string, v: View): Layout {
	const view = {
		x: Math.round(v.x),
		y: Math.round(v.y),
		zoom: Math.round(clamp(v.zoom, 0.1, 4) * 1000) / 1000
	};
	const s = l.workspaces.find((x) => x.id === tab);
	if (!s || JSON.stringify(s.view) === JSON.stringify(view)) return l;
	return { ...l, workspaces: l.workspaces.map((x) => (x === s ? { ...s, view } : x)) };
}

const withItem = (l: Layout, here: Space, item: Item): Layout => ({
	...l,
	workspaces: l.workspaces.map((s) => (s === here ? { ...s, items: [...s.items, item] } : s))
});

/** A heading or a frame on the active board, centred on `c` (else below the others); l itself when the board is full. */
export function addItem(l: Layout, id: string, kind: 'heading' | 'frame', c?: Point): Layout {
	const here = activeSpace(l);
	if (here.items.length >= MAX_ITEMS) return l;
	return withItem(
		l,
		here,
		kind === 'heading'
			? { id, kind, text: 'Heading', ...spot(here, 400, 48, c) }
			: { id, kind, title: 'Frame', ...spot(here, 800, 480, c) }
	);
}

/** A new widget on the active board, centred on `c` (else below the others); it runs once, as a click. */
export function addWidget(
	l: Layout,
	id: string,
	title: string,
	spec: WidgetSpec,
	c?: Point
): { layout: Layout; send: ToThalamus | null } {
	const here = activeSpace(l);
	if (widgetsOf(here).length >= MAX_WIDGETS || here.items.length >= MAX_ITEMS)
		return { layout: l, send: null };
	const box: WidgetItem = {
		id,
		kind: 'widget',
		title: title.slice(0, 120),
		spec,
		...spot(here, W, H, c)
	};
	return {
		layout: withItem(l, here, box),
		send: { t: 'widget', widget: id, spec: lensed(spec, here.lens), trigger: 'click' }
	};
}

/** addWidget, and the widget's state: its spec, not run yet. */
export function placed(
	l: Layout,
	w: Widgets,
	id: string,
	title: string,
	spec: WidgetSpec,
	c?: Point
): { layout: Layout; w: Widgets; send: ToThalamus | null } {
	const r = addWidget(l, id, title, spec, c);
	if (!r.send) return { layout: l, w, send: null };
	return {
		layout: r.layout,
		w: { ...w, [id]: { component: null, error: null, at: 0, spec } },
		send: r.send
	};
}

/** The person's click on a render's pin: a widget of a copy of that spec, titled as the render, on the
 *  active board ("Sem") or, given `tab`, on a new board of that id inside it ("Nová plocha"). Nothing for no pin or no room. */
export function pin(
	l: Layout,
	w: Widgets,
	id: string,
	m: ToShell,
	tab?: string,
	c?: Point
): { layout: Layout; w: Widgets; send: ToThalamus | null } {
	if (m.t !== 'render' || !m.pin) return { layout: l, w, send: null };
	const p = m.component.props as { title?: string; name?: string };
	// msg lives in $state: a Proxy, which structuredClone refuses. JSON is all a spec is.
	const spec = JSON.parse(JSON.stringify(m.pin)) as WidgetSpec;
	const title = p.title || p.name || tableOf(spec);
	if (tab === undefined) return placed(l, w, id, title, spec, c);
	const fresh = addSpace(l, tab, title, l.active, c);
	return fresh === l ? { layout: l, w, send: null } : placed(fresh, w, id, title, spec);
}

export const removeItem = (l: Layout, id: string): Layout =>
	mapItems(l, (is) => is.filter((i) => i.id !== id));

/** A new active workspace: a root, or given `parent` a board inside it, with its card there (centred on `c`). l when there is no room. */
export function addSpace(l: Layout, id: string, name: string, parent?: string, c?: Point): Layout {
	if (l.workspaces.length >= MAX_SPACES) return l;
	const up = l.workspaces.find((s) => s.id === parent);
	const space: Space = { id, name: name.slice(0, 40), items: [] };
	if (!up) return { ...l, active: id, workspaces: [...l.workspaces, space] };
	if (up.items.length >= MAX_ITEMS || chain(l, up.id).length >= MAX_DEPTH) return l;
	const card: BoardItem = {
		id: `b-${id}`.slice(0, 64),
		kind: 'board',
		board: id,
		...spot(up, 240, 96, c)
	};
	const shown = withItem(l, up, card);
	return { ...shown, active: id, workspaces: [...shown.workspaces, { ...space, parent: up.id }] };
}

/** `id` and every board inside it, the card that opened it too; the active one falls back to its parent. */
export function removeSpace(l: Layout, id: string): Layout {
	const gone = new Set(l.workspaces.filter((s) => chain(l, s.id).includes(id)).map((s) => s.id));
	const rest = l.workspaces
		.filter((s) => !gone.has(s.id))
		.map((s) => ({ ...s, items: s.items.filter((i) => i.kind !== 'board' || !gone.has(i.board)) }));
	if (!rest.length) return l;
	const up = l.workspaces.find((s) => s.id === id)?.parent;
	const active = gone.has(l.active) ? (up ?? rest[0].id) : l.active;
	return { ...l, workspaces: rest, active };
}

const run = (w: WidgetState): 'restore' | 'table_changed' =>
	w.stale ? 'table_changed' : 'restore';

/** The widgets on the shown board that are stale or never ran, sent now; the others wait to be shown. */
function due(l: Layout, w: Widgets): { w: Widgets; send: Send } {
	const out = { ...w };
	const send: Send = [];
	const here = activeSpace(l);
	for (const box of widgetsOf(here)) {
		const s = out[box.id];
		if (!s || !(s.stale || s.due)) continue;
		send.push({ t: 'widget', widget: box.id, spec: lensed(box.spec, here.lens), trigger: run(s) });
		out[box.id] = { ...s, stale: false, due: false };
	}
	return { w: out, send };
}

/** A saved layout came back: every widget remembers its spec, only the active board runs. */
export function restore(l: Layout): { w: Widgets; send: Send } {
	const w: Widgets = {};
	for (const s of l.workspaces)
		for (const box of widgetsOf(s))
			w[box.id] = { component: null, error: null, at: 0, spec: box.spec, due: true };
	return due(l, w);
}

/** Show `tab`; its stale or never-run widgets run now. */
export function show(
	l: Layout,
	w: Widgets,
	tab: string
): { layout: Layout; w: Widgets; send: Send } {
	if (!l.workspaces.some((s) => s.id === tab)) return { layout: l, w, send: [] };
	const layout = { ...l, active: tab };
	return { layout, ...due(layout, w) };
}

/** A write landed in `table`: the active board's readers re-run, the rest go stale. */
export function onTableChanged(l: Layout, w: Widgets, table: string): { w: Widgets; send: Send } {
	const here = activeSpace(l);
	const r = staleOrSend(
		w,
		table,
		widgetsOf(here).map((b) => b.id)
	);
	return {
		w: r.w,
		send: r.send.map((m) => (m.t === 'widget' ? { ...m, spec: lensed(m.spec, here.lens) } : m))
	};
}

/** The person set lens condition `i` of `tab`: every widget there re-runs, as a click. */
export function setLens(
	l: Layout,
	tab: string,
	i: number,
	value: string
): { layout: Layout; send: Send } {
	const s = l.workspaces.find((x) => x.id === tab);
	if (!s?.lens?.[i]) return { layout: l, send: [] };
	const lens = s.lens.map((c, j) => (j === i ? { ...c, value: value.slice(0, 120) } : c));
	return {
		layout: { ...l, workspaces: l.workspaces.map((x) => (x === s ? { ...s, lens } : x)) },
		send: widgetsOf(s).map((b) => ({
			t: 'widget',
			widget: b.id,
			spec: lensed(b.spec, lens),
			trigger: 'click'
		}))
	};
}

/** The person's click on "Place on a new board": a board inside the active one, with the offer's lens, two widgets a
 *  row; each runs once, as a click. `here` ("Place here"): the widgets join the active board below its own. */
export function placeOffer(
	l: Layout,
	w: Widgets,
	tab: string,
	d: DashboardProps,
	id: () => string,
	here = false
): { layout: Layout; w: Widgets; send: Send } {
	const into = activeSpace(l);
	const room = here
		? Math.min(MAX_WIDGETS - widgetsOf(into).length, MAX_ITEMS - into.items.length)
		: addSpace(l, tab, '', l.active) !== l
			? MAX_WIDGETS
			: 0;
	if (room <= 0) return { layout: l, w, send: [] };
	// The offer lives in $state: a Proxy. JSON is all an offer is.
	const { name, lens, widgets } = JSON.parse(JSON.stringify(d)) as DashboardProps;
	// ponytail: "here" bakes the offer's set lens into each spec and drops an unset one; merge lenses if people ask.
	const y0 = here ? below(into) : 0;
	const boxes: WidgetItem[] = widgets.slice(0, room).map((x, i) => ({
		id: id(),
		kind: 'widget',
		title: x.title.slice(0, 120),
		spec: here ? lensed(x.spec, lens) : x.spec,
		...place({ x: (i % 2) * (W + SNAP), y: y0 + Math.floor(i / 2) * (H + SNAP), w: W, h: H })
	}));
	const out = { ...w };
	for (const b of boxes) out[b.id] = { component: null, error: null, at: 0, spec: b.spec };
	const sent = here ? into.lens : lens;
	return {
		layout: here
			? {
					...l,
					workspaces: l.workspaces.map((s) =>
						s === into ? { ...s, items: [...s.items, ...boxes] } : s
					)
				}
			: patch(addSpace(l, tab, name, l.active), tab, { lens, items: boxes }),
		w: out,
		send: boxes.map((b) => ({
			t: 'widget',
			widget: b.id,
			spec: lensed(b.spec, sent),
			trigger: 'click'
		}))
	};
}

const patch = (l: Layout, id: string, set: Partial<Space>): Layout => ({
	...l,
	workspaces: l.workspaces.map((s) => (s.id === id ? { ...s, ...set } : s))
});

/** An approval waits: the chat opens on top, since its card lives there. */
export const approvalArrived = (l: Layout): { layout: Layout; top: 'chat' } => ({
	layout: { ...l, chat: { ...l.chat, open: true } },
	top: 'chat'
});

/** The chat inside the viewport, at least 280×240; a fresh one (w 0) docks top right. */
export function clampChat(c: Chat, vp: { w: number; h: number }): Chat {
	const fresh = c.w === 0 || c.h === 0;
	const w = clamp(fresh ? 380 : c.w, Math.min(280, vp.w), vp.w);
	const h = clamp(fresh ? Math.min(560, vp.h - 32) : c.h, Math.min(240, vp.h), vp.h);
	const x = fresh ? vp.w - w - 16 : c.x,
		y = fresh ? 16 : c.y;
	return { x: clamp(x, 0, vp.w - w), y: clamp(y, 0, vp.h - h), w, h, open: c.open };
}

/** How old a widget's answer is, by the pupil's own clock. */
export function age(s: WidgetState | undefined, now: number): string {
	if (s?.stale) return 'stale: the table changed';
	if (!s || s.at === 0) return 'not run yet';
	const sec = Math.max(0, Math.round((now - s.at) / 1000));
	return sec < 60
		? `${sec} s ago`
		: sec < 3600
			? `${Math.round(sec / 60)} min ago`
			: `${Math.round(sec / 3600)} h ago`;
}
