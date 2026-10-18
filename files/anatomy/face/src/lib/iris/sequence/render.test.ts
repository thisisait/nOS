// A sequence the model shows (renderers.rs Sequence): lifelines widened until every label
// fits, so at the caps (8 participants, 40 steps, the longest labels) every <text> stays
// inside the viewBox and no two overlap. Read from the markup, measured by the layout's own
// glyph-class estimate (an independent font would need a browser).
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Sequence from '../Sequence.svelte';
import { layoutSequence, measure, type SequenceProps } from './layout';

const html = (sequence: SequenceProps) => render(Sequence, { props: { sequence } }).body;

const unescape = (s: string) =>
	s
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.replace(/&amp;/g, '&');

/** Every <text> as drawn: its box from x, y (baseline), anchor and font-size. */
function texts(h: string) {
	return [...h.matchAll(/<text([^>]*)>([^<]*)<\/text>/g)].map(([, a, raw]) => {
		const at = (k: string) => a.match(new RegExp(`${k}="([^"]*)"`))?.[1];
		const t = unescape(raw);
		const size = Number(at('font-size'));
		const [x, y, w] = [Number(at('x')), Number(at('y')), measure(t, size)];
		const anchor = at('text-anchor') ?? 'start';
		const lo = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x;
		return { t, lo, hi: lo + w, top: y - size, bottom: y };
	});
}

const box = (h: string) => {
	const m = h.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
	expect(m, 'the svg has a viewBox').toBeTruthy();
	return { W: Number(m![1]), H: Number(m![2]) };
};

const path: SequenceProps = {
	title: 'An approval',
	participants: ['pupil', 'thalamus', 'KEAP'],
	steps: [
		{ phase: 'propose' },
		{ from: 'pupil', to: 'thalamus', text: 'close the row' },
		{ from: 'thalamus', to: 'KEAP', text: 'query_rows' },
		{ from: 'KEAP', to: 'thalamus', text: '1 row', dashed: true },
		{ note: 'the person decides', over: ['pupil'] },
		{ from: 'thalamus', to: 'thalamus', text: 'check caps' }
	]
};

/** The caps at their worst: 8 wide 40-char names, 40 steps of 120-char messages near and far, self calls, wide notes, long phases. */
const W40 = (i: number) => `W${i}`.padEnd(40, 'MW');
const crowd: SequenceProps = {
	title: 'Everyone talks',
	participants: Array.from({ length: 8 }, (_, i) => W40(i)),
	steps: Array.from({ length: 40 }, (_, i): SequenceProps['steps'][number] => {
		const p = (k: number) => W40(k % 8);
		if (i % 10 === 4)
			return { note: `note ${i} `.padEnd(200, 'MW m'), over: i % 20 === 4 ? [p(0)] : [p(7)] };
		if (i % 10 === 9) return { phase: `phase ${i} `.padEnd(60, 'Wm') };
		if (i % 7 === 0) return { from: p(i), to: p(i), text: `self ${i} `.padEnd(120, 'MW') };
		if (i % 5 === 3) return { note: `two ${i} `.padEnd(200, 'W'), over: [p(i), p(i + 3)] };
		return {
			from: p(i),
			to: p(i * 3 + 1),
			text: `message ${i} `.padEnd(120, 'MWmw'),
			dashed: i % 2 === 0
		};
	})
};

/** Two short lifelines under a phase wider than everything else: the phase sets W. */
const narrow: SequenceProps = {
	participants: ['a', 'b'],
	steps: [
		{ phase: 'W@% '.repeat(15).trim() },
		{ from: 'a', to: 'b', text: 'x' },
		{ note: 'n', over: ['a'] }
	]
};

describe('the sequence layout', () => {
	it('the same sequence lands in the same place, and draws the same markup', () => {
		expect(layoutSequence(crowd)).toEqual(layoutSequence(crowd));
		expect(html(crowd)).toBe(html(crowd));
	});

	for (const [name, q] of [
		['an approval', path],
		['8 participants with the longest labels', crowd],
		['a phase wider than the diagram', narrow]
	] as const)
		it(`every label is inside the viewBox and no two overlap: ${name}`, () => {
			const h = html(q);
			const { W, H } = box(h);
			const ts = texts(h);
			const words = [
				...q.participants,
				...q.steps.map((s) => ('text' in s ? s.text : 'note' in s ? s.note : s.phase))
			];
			expect(ts.map((t) => t.t).sort()).toEqual(words.sort());
			for (const t of ts) {
				expect(t.lo, t.t).toBeGreaterThanOrEqual(0);
				expect(t.hi, t.t).toBeLessThanOrEqual(W);
				expect(t.top, t.t).toBeGreaterThanOrEqual(0);
				expect(t.bottom, t.t).toBeLessThanOrEqual(H);
			}
			for (const [i, a] of ts.entries())
				for (const b of ts.slice(i + 1)) {
					const apart = a.hi <= b.lo || b.hi <= a.lo || a.bottom <= b.top || b.bottom <= a.top;
					expect(apart, `${a.t.slice(0, 20)} overlaps ${b.t.slice(0, 20)}`).toBe(true);
				}
		});

	it('a message label fits between the lifelines it joins', () => {
		const g = layoutSequence(crowd);
		const x = new Map(g.actors.map((a) => [a.name, a.x]));
		for (const s of g.steps)
			if (s.kind === 'message' && s.from !== s.to) {
				const [l, r] = [x.get(s.from)!, x.get(s.to)!].sort((p, q) => p - q);
				expect(r - l, s.label.t.slice(0, 20)).toBeGreaterThanOrEqual(measure(s.label.t, g.FONT));
			}
	});

	it('a phase wider than the diagram widens it, its pill inside, the lifelines centred under it', () => {
		const g = layoutSequence(narrow);
		const ph = g.steps.find((s) => s.kind === 'phase')!;
		if (ph.kind !== 'phase') throw new Error('no phase');
		expect(ph.rect.x).toBeGreaterThanOrEqual(0);
		expect(ph.rect.x + ph.rect.w).toBeLessThanOrEqual(g.W);
		expect(ph.rect.w).toBeGreaterThanOrEqual(measure(ph.label.t, g.FONT));
		expect(ph.rule.x1).toBeGreaterThanOrEqual(0);
		expect(ph.rule.x2).toBeLessThanOrEqual(g.W);
		const [a, b] = g.actors;
		const lo = a.box.x,
			hi = b.box.x + b.box.w;
		expect(Math.abs(lo - (g.W - hi)), `margins ${lo} | ${g.W - hi}`).toBeLessThanOrEqual(1);
	});

	it('every step is one fixed-height row', () => {
		const g = layoutSequence(path);
		const tops = g.steps.map((s) => s.top);
		expect(tops.slice(1).map((t, i) => t - tops[i])).toEqual(Array(tops.length - 1).fill(g.STEP));
	});

	it('a glyph is measured by its class: wide, capital, narrow, CJK', () => {
		expect(measure('W', 10)).toBeGreaterThan(measure('a', 10));
		expect(measure('a', 10)).toBeGreaterThan(measure('i', 10));
		expect(measure('漢', 10)).toBe(10);
		expect(measure('', 10)).toBe(0);
	});

	// Helvetica's advance widths (Adobe Core14 AFM, per 1000 em): the reference sans the estimate must not undercut.
	const HELVETICA: Record<string, number> = Object.fromEntries(
		[
			...' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~'
		].map((c, i) => [
			c,
			[
				278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556,
				556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722,
				722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722,
				667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
				556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500,
				500, 334, 260, 334, 584
			][i]
		])
	);

	it('no printable ASCII glyph is measured narrower than Helvetica draws it', () => {
		expect(Object.keys(HELVETICA).length).toBe(95);
		const short = Object.entries(HELVETICA)
			.filter(([c, w]) => measure(c, 1000) < w)
			.map(([c, w]) => `${c} ${measure(c, 1000)} < ${w}`);
		expect(short).toEqual([]);
	});
});

describe('a sequence is SVG lifelines and arrows, every word as text', () => {
	it('one <path> per message, dashed for a reply, each with its <title>', () => {
		const h = html(path);
		const arrows = h.match(/<path[^>]*class="msg[^"]*"[^>]*>\s*<title>[^<]*<\/title>/g) ?? [];
		expect(arrows).toHaveLength(4);
		expect(h.match(/<path[^>]*class="msg[^"]*dashed/g)).toHaveLength(1);
		expect(h).toContain('KEAP → thalamus: 1 row (reply)');
		expect(h.match(/<line[^>]*class="lifeline/g)).toHaveLength(3);
	});

	it('a note and a phase are a box and a rule, each with its <title>', () => {
		const h = html(path);
		expect(h).toMatch(
			/<rect[^>]*class="note[^"]*"[^>]*>\s*<title>note over pupil: the person decides<\/title>/
		);
		expect(h).toMatch(/<line[^>]*class="phase[^"]*"[^>]*>\s*<title>phase: propose<\/title>/);
	});

	it('a labelled group, not an image', () => {
		const svg = html(path).match(/<svg[^>]*>/)?.[0] ?? '';
		expect(svg).toContain('role="group"');
		expect(svg).toMatch(/aria-label="An approval — sequence, 3 participants and 6 steps"/);
	});

	it('text nodes only: no link, no foreign markup, no script', () => {
		const h = html({
			participants: ['<script>x</script>', 'b'],
			steps: [{ from: '<script>x</script>', to: 'b', text: '<img onerror=1>' }]
		});
		expect(h).not.toMatch(/<(a|foreignObject|script|img|iframe)[\s>]/);
		expect(h).toContain('&lt;img');
	});
});
