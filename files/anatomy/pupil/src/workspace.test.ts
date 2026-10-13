// The workspace: tabs of widgets on a 12-column grid and a floating chat (genui I5h).
// Every move, resize, restore and re-run goes through these pure reducers.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { WidgetSpec } from './wire';
import type { Widgets } from './widgets';
import {
	addWidget, age, approvalArrived, byKey, byPointer, clampChat, onTableChanged, place, removeWidget, restore, show,
	type Layout
} from './workspace';

const FIXTURE = new URL('../../contracts/workspace-layout.fixture.json', import.meta.url);
const fx = JSON.parse(readFileSync(FIXTURE, 'utf8')) as { samples: { case: string; layout: Layout }[] };
const sample = (i: number) => structuredClone(fx.samples[i].layout);
const inGrid = (l: Layout) =>
	l.workspaces.every((s) => s.widgets.every((w) => w.x >= 0 && w.x + w.w <= 12 && w.w >= 2 && w.h >= 2 && w.h <= 40 && w.y >= 0 && w.y <= 400));
const rows: WidgetSpec = { rows: { table: 'expenses' } };

describe('place snaps to grid units', () => {
	it('rounds to integers and clamps to 12 columns', () => {
		expect(place({ x: 3.4, y: 1.6, w: 4.5, h: 2.2 })).toEqual({ x: 3, y: 2, w: 5, h: 2 });
		expect(place({ x: 11, y: 0, w: 4, h: 8 }), 'a box past the edge slides back').toEqual({ x: 8, y: 0, w: 4, h: 8 });
		expect(place({ x: -3, y: -2, w: 1, h: 99 })).toEqual({ x: 0, y: 0, w: 2, h: 40 });
		expect(place({ x: 0, y: 0, w: 30, h: 8 }).w).toBe(12);
		expect(place({ x: 0, y: 999, w: 2, h: 2 }).y).toBe(400);
	});
});

describe('move and resize keep every widget inside the grid', () => {
	const g = { x: 6, y: 2, w: 6, h: 8 };
	it('by pointer, in pixels snapped to units', () => {
		expect(byPointer(g, 'move', -95, 41, 50, 48)).toEqual({ x: 4, y: 3, w: 6, h: 8 });
		expect(byPointer(g, 'move', 400, 0, 50, 48).x, 'cannot leave on the right').toBe(6);
		expect(byPointer(g, 'resize', 300, -1000, 50, 48), 'resize stops at column 12, at h 2').toEqual({ x: 6, y: 2, w: 6, h: 2 });
		expect(byPointer(g, 'resize', -1000, 0, 50, 48).w).toBe(2);
	});
	it('by arrow keys: arrows move, shift+arrows resize', () => {
		expect(byKey(g, 'ArrowLeft', false)).toEqual({ ...g, x: 5 });
		expect(byKey(g, 'ArrowDown', false)).toEqual({ ...g, y: 3 });
		expect(byKey(g, 'ArrowRight', false), 'already at the edge').toEqual(g);
		expect(byKey(g, 'ArrowLeft', true)).toEqual({ ...g, w: 5 });
		expect(byKey(g, 'ArrowUp', true)).toEqual({ ...g, h: 7 });
		expect(byKey({ ...g, x: 0, w: 2 }, 'ArrowLeft', true), 'w stays >= 2').toEqual({ ...g, x: 0, w: 2 });
		expect(byKey(g, 'Enter', false)).toBeNull();
	});
	it('add and remove keep the layout valid', () => {
		let l = sample(0);
		const before = l.workspaces[0].widgets.length;
		const a = addWidget(l, 'wnew', 'New', rows);
		expect(inGrid(a.layout)).toBe(true);
		expect(a.layout.workspaces[0].widgets.length).toBe(before + 1);
		expect(a.send, 'a new widget runs once, as a click').toEqual({ t: 'widget', widget: 'wnew', spec: rows, trigger: 'click' });
		const added = a.layout.workspaces[0].widgets.at(-1)!;
		const below = Math.max(...l.workspaces[0].widgets.map((w) => w.y + w.h));
		expect(added.y, 'lands below the others, never on top of one').toBe(below);
		l = removeWidget(a.layout, 'wnew');
		expect(l.workspaces[0].widgets.length).toBe(before);
	});
});

describe('re-runs: the active tab only', () => {
	const ran = (l: Layout): Widgets => {
		const w: Widgets = {};
		for (const s of l.workspaces) for (const x of s.widgets) w[x.id] = { component: { kind: 'markdown', props: { text: '' } }, error: null, at: 1, spec: x.spec };
		return w;
	};
	it('a table change re-runs the active tab and marks the others stale', () => {
		const l = sample(1); // active "b": w2 chart on expenses, w3 rows on notes; "a": w1 rows on expenses
		const r = onTableChanged(l, ran(l), 'expenses');
		expect(r.send.map((m) => m.t === 'widget' && m.widget)).toEqual(['w2']);
		expect(r.send.every((m) => m.t === 'widget' && m.trigger === 'table_changed')).toBe(true);
		expect(r.w.w1.stale).toBe(true);
		expect(r.w.w3.stale).toBeFalsy();
	});
	it('a shown tab runs its stale widgets, and only them', () => {
		const l = sample(1);
		const changed = onTableChanged(l, ran(l), 'expenses');
		const s = show(l, changed.w, 'a');
		expect(s.layout.active).toBe('a');
		expect(s.send).toEqual([{ t: 'widget', widget: 'w1', spec: rows, trigger: 'table_changed' }]);
		expect(show(s.layout, s.w, 'a').send, 'showing it again sends nothing new').toEqual([]);
		expect(show(l, changed.w, 'nowhere').layout.active, 'an unknown tab is not shown').toBe('b');
	});
	it('a restored layout re-sends exactly the active tab, as restore', () => {
		for (const c of fx.samples) {
			const r = restore(c.layout);
			const active = c.layout.workspaces.find((s) => s.id === c.layout.active)!.widgets;
			expect(r.send, c.case).toEqual(active.map((w) => ({ t: 'widget', widget: w.id, spec: w.spec, trigger: 'restore' })));
			const off = c.layout.workspaces.filter((s) => s.id !== c.layout.active).flatMap((s) => s.widgets);
			for (const w of off) expect(r.w[w.id]?.spec, `${c.case}: ${w.id} remembers its spec`).toEqual(w.spec);
		}
		const two = restore(sample(1));
		const later = show(sample(1), two.w, 'a');
		expect(later.send, 'a never-run widget runs when its tab is shown, as restore').toEqual([{ t: 'widget', widget: 'w1', spec: rows, trigger: 'restore' }]);
	});
});

describe('the chat panel', () => {
	const vp = { w: 1280, h: 860 };
	it('clampChat keeps the panel inside the viewport', () => {
		for (const c of [
			{ x: 5000, y: 5000, w: 380, h: 560, open: true },
			{ x: -400, y: -50, w: 380, h: 560, open: true },
			{ x: 0, y: 0, w: 4000, h: 4000, open: false },
			{ x: 0, y: 0, w: 0, h: 0, open: true }
		]) {
			const k = clampChat(c, vp);
			expect(k.x >= 0 && k.y >= 0 && k.x + k.w <= vp.w && k.y + k.h <= vp.h, JSON.stringify(k)).toBe(true);
			expect(k.w >= 280 && k.h >= 240, 'never shrinks to nothing').toBe(true);
			expect(k.open).toBe(c.open);
		}
		expect(clampChat({ x: 100, y: 100, w: 380, h: 560, open: true }, vp), 'on screen: unchanged').toEqual({ x: 100, y: 100, w: 380, h: 560, open: true });
		const tiny = clampChat({ x: 900, y: 300, w: 380, h: 560, open: true }, { w: 720, h: 600 });
		expect(tiny.x + tiny.w <= 720 && tiny.y + tiny.h <= 600).toBe(true);
	});
	it('an approval request opens the chat and raises it', () => {
		const l = sample(1);
		expect(l.chat.open).toBe(false);
		const r = approvalArrived(l);
		expect(r.layout.chat.open).toBe(true);
		expect(r.top).toBe('chat');
	});
});

describe('age', () => {
	it('says how old an answer is, or that it went stale', () => {
		expect(age({ component: null, error: null, at: 1000 }, 13_400)).toBe('12 s ago');
		expect(age({ component: null, error: null, at: 0 }, 180_000)).toBe('3 min ago');
		expect(age({ component: null, error: null, at: 1000, stale: true }, 2000)).toBe('stale: the table changed');
		expect(age(undefined, 1)).toBe('not run yet');
	});
});
