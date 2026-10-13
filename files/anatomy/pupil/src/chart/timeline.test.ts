// A time-scaled timeline (renderers.rs Timeline) as pure geometry: which drawing, rows by lane,
// spans and instants on one time axis, the zoom on x only, every label inside the box.
import { describe, expect, it } from 'vitest';
import { isDate, layoutTimeline, timed, type Item } from './timeline';
import { IDENTITY, wheel } from './zoom';

const items: Item[] = [
	{ when: '2026-10-01', until: '2026-10-05', title: 'lanes and gates', lane: 'thalamus' },
	{ when: '2026-10-06', until: '2026-10-09', title: 'chart axes', lane: 'pupil' },
	{ when: '2026-10-13', title: 'timeline', lane: 'pupil', hi: true },
];
const day = (s: string) => Date.parse(s);

describe('a timeline is time-scaled only when every date is a date', () => {
	it('matches the thalamus date pattern (renderers.rs is_date)', () => {
		for (const ok of ['2026-10-13', '2024-02-29', '2026-12-31T23:59:59Z', '2026-01-01T00:00:00+02:00', '2026-01-01T00:00:00-11:30'])
			expect(isDate(ok), ok).toBe(true);
		for (const bad of ['2026-02-30', '2025-02-29', '2026-13-01', '2026-10-1', '2026/10/13', '2026-10-13T10:00', '2026-10-13T10:00:00',
			'2026-10-13T24:00:00Z', '2026-10-13T10:00:00.5Z', ' 2026-10-13', 'Q1', 'yesterday', ''])
			expect(isDate(bad), bad).toBe(false);
	});

	it('every when, and every until given, must be a date', () => {
		expect(timed(items)).toBe(true);
		expect(timed([...items, { when: 'Q1', title: 'x' }])).toBe(false);
		expect(timed([{ when: '2026-10-01', until: 'later', title: 'x' }])).toBe(false);
	});
});

describe('the time layout', () => {
	const g = layoutTimeline(items, 320, IDENTITY, day('2026-10-07'));

	it('one row per lane, named in the gutter, in first-seen order', () => {
		expect(g.lanes.map((l) => l.t)).toEqual(['thalamus', 'pupil']);
		const rowOf = (i: number) => g.marks[i].y;
		expect(rowOf(1)).toBe(rowOf(2));
		expect(rowOf(0)).not.toBe(rowOf(1));
	});

	it('a span is a bar from when to until, an instant a dot, in date order on x', () => {
		const [a, b, c] = g.marks;
		expect(a.w).toBeGreaterThan(0);
		expect(b.w).toBeGreaterThan(0);
		expect(c.w).toBeUndefined();
		expect(a.x + a.w!).toBeLessThan(b.x);
		expect(b.x + b.w!).toBeLessThan(c.x);
		expect(c.tip).toBe('timeline · 2026-10-13 hi [pupil]');
		expect(a.tip).toBe('lanes and gates · 2026-10-01 → 2026-10-05 [thalamus]');
	});

	it('an item without a lane has its own row', () => {
		const own = layoutTimeline([{ when: '2026-10-01', title: 'a' }, { when: '2026-10-02', title: 'b' }], 320, IDENTITY, 0);
		expect(own.marks[0].y).not.toBe(own.marks[1].y);
	});

	it('the now rule is drawn only when now is inside the range', () => {
		expect(g.now).not.toBeNull();
		expect(g.now!).toBeGreaterThan(g.marks[1].x);
		expect(g.now!).toBeLessThan(g.marks[1].x + g.marks[1].w!);
		expect(layoutTimeline(items, 320, IDENTITY, day('2026-11-01')).now).toBeNull();
		expect(layoutTimeline(items, 320, IDENTITY, day('2026-09-01')).now).toBeNull();
	});

	it('a wheel at a mark keeps that mark where it is, and zooms only x', () => {
		const at = g.marks[1].x - g.L;
		const z = wheel(IDENTITY, [at, 40], -300, g.box);
		const zoomed = layoutTimeline(items, 320, z, 0);
		expect(z.k).toBe(2);
		expect(z.ty).toBe(0);
		expect(Math.abs(zoomed.marks[1].x - g.marks[1].x)).toBeLessThan(0.2);
		expect(zoomed.marks[1].w!).toBeCloseTo(g.marks[1].w! * 2, 0);
		expect(zoomed.marks[1].y).toBe(g.marks[1].y);
	});

	it('every label stays inside the box, 30 items over a year, in long lanes', () => {
		const many: Item[] = Array.from({ length: 30 }, (_, i) => ({
			when: new Date(Date.UTC(2026, 0, 1 + i * 12)).toISOString().slice(0, 10),
			until: new Date(Date.UTC(2026, 0, 6 + i * 12)).toISOString().slice(0, 10),
			title: `a rather long item title number ${i}`,
			lane: `lane ${'x'.repeat(30)} ${i % 4}`,
		}));
		for (const zoom of [IDENTITY, { k: 6, tx: -500, ty: 0 }]) {
			const t = layoutTimeline(many, 320, zoom, 0);
			const texts = [...t.lanes.map((l) => ({ t: l.t, x: l.x, anchor: 'end' })), ...t.xLabels.map((l) => ({ ...l, anchor: 'middle' })),
				...t.marks.flatMap((m) => (m.label ? [{ ...m.label, anchor: 'start' }] : []))];
			// At rest every row is labelled; zoomed in, most items are out of view and drop their label.
			expect(texts.length).toBeGreaterThan(zoom === IDENTITY ? 30 : 4);
			for (const l of texts) {
				const w = l.t.length * t.FONT * 0.6;
				const lo = l.anchor === 'end' ? l.x - w : l.anchor === 'middle' ? l.x - w / 2 : l.x;
				expect(lo, l.t).toBeGreaterThanOrEqual(0);
				expect(lo + w, l.t).toBeLessThanOrEqual(t.W);
			}
			for (const m of t.marks) if (m.label) expect(m.label.x, m.label.t).toBeGreaterThanOrEqual(t.L);
		}
	});
});
