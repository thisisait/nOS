// Tree and timeline (renderers.rs): every label is a text node. One root with
// 2-4 children is an org chart; anything else is a nested list. A timeline is
// horizontal up to 6 items and vertical beyond. hi is a word, not only a colour.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Component from './Component.svelte';
import Timeline from './Timeline.svelte';

const text = (html: string) =>
	html
		.replace(/<[^>]*>/g, ' ')
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&amp;/g, '&')
		.replace(/\s+/g, ' ')
		.trim();
const draw = (component: object) => {
	const html = render(Component, { props: { component: component as never } }).body;
	return { html, text: text(html) };
};

describe('tree and timeline are text, laid out by the shape', () => {
	it('draws every tree label as text, as an org chart for one root with 2-4 children', () => {
		const g = draw({
			kind: 'tree',
			props: {
				title: 'Roadmap',
				nodes: [{ label: 'nOS', children: [{ label: 'pupil', note: 'the eye' }, { label: 'keap' }] }],
			},
		});
		for (const s of ['Roadmap', 'nOS', 'pupil', 'the eye', 'keap']) expect(g.text).toContain(s);
		expect(g.html).toContain('data-layout="org"');
		expect(g.html).not.toContain('<script');
	});

	it('a forest, or a root outside 2-4 children, is a nested list', () => {
		const forest = draw({ kind: 'tree', props: { nodes: [{ label: 'only' }, { label: 'other' }] } });
		expect(forest.text).toContain('only');
		expect(forest.text).toContain('other');
		expect(forest.html).toContain('data-layout="list"');
		const one = draw({ kind: 'tree', props: { nodes: [{ label: 'root', children: [{ label: 'child' }] }] } });
		expect(one.html).toContain('data-layout="list"');
	});

	it('a label is text, never markup', () => {
		const g = draw({ kind: 'tree', props: { nodes: [{ label: '<script>x</script>' }] } });
		expect(g.html).not.toContain('<script');
		expect(g.text).toContain('<script>x</script>');
	});

	// Re-pinned (I5c): a timeline whose every when is a date is drawn on a time axis; in order only otherwise.
	it('a timeline of at most 6 is horizontal, and hi is a word', () => {
		const g = draw({
			kind: 'timeline',
			props: {
				title: 'History',
				items: [
					{ when: 'Q3', title: 'I4a landed', note: 'query_rows' },
					{ when: 'Q4', title: 'chart', hi: true },
				],
			},
		});
		for (const s of ['History', 'Q3', 'I4a landed', 'query_rows', 'Q4', 'chart', 'hi']) expect(g.text).toContain(s);
		expect(g.html).toContain('data-layout="horizontal"');
	});

	it('a dated timeline is drawn on a time axis, every word still text', () => {
		const g = draw({
			kind: 'timeline',
			props: {
				title: 'History',
				items: [
					{ when: '2026-10-12', title: 'I4a landed', note: 'query_rows' },
					{ when: '2026-10-13', title: 'chart', hi: true },
				],
			},
		});
		for (const s of ['History', '2026-10-12', 'I4a landed', 'query_rows', '2026-10-13', 'chart', 'hi']) expect(g.text).toContain(s);
		expect(g.html).toContain('data-layout="time"');
		expect(g.html).not.toContain('data-layout="horizontal"');
	});

	it('a timeline past 6 items is vertical', () => {
		const items = Array.from({ length: 7 }, (_, i) => ({ when: `d${i}`, title: `t${i}` }));
		const g = draw({ kind: 'timeline', props: { items } });
		expect(g.text).toContain('t6');
		expect(g.html).toContain('data-layout="vertical"');
	});

	const spans = [
		{ when: '2026-10-01', until: '2026-10-05', title: 'lanes and gates', lane: 'thalamus' },
		{ when: '2026-10-06', until: '2026-10-09', title: 'chart axes', lane: 'pupil' },
		{ when: '2026-10-13', title: 'timeline', lane: 'pupil', hi: true },
	];

	it('three dated items: a <rect> per span, a <circle> per instant, lanes as <text>', () => {
		const g = draw({ kind: 'timeline', props: { title: 'I5', items: spans } });
		expect(g.html.match(/<rect[^>]*class="span/g)?.length).toBe(2);
		expect(g.html.match(/<circle[^>]*class="instant/g)?.length).toBe(1);
		const texts = [...g.html.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1].trim());
		expect(texts).toContain('thalamus');
		expect(texts).toContain('pupil');
		for (const s of ['2026-10-05', 'chart axes', 'hi']) expect(g.text).toContain(s);
		const svg = g.html.match(/<svg[^>]*>/)?.[0] ?? '';
		expect(svg).toContain('role="group"');
		expect(g.html).not.toContain('role="img"');
		for (const m of g.html.match(/<(rect|circle)[^>]*class="(span|instant)[^>]*>/g) ?? []) expect(m).toContain('tabindex="0"');
	});

	it('three items named Q1/Q2/Q3 keep the ordinal drawing', () => {
		const g = draw({ kind: 'timeline', props: { items: ['Q1', 'Q2', 'Q3'].map((when) => ({ when, title: `in ${when}` })) } });
		expect(g.html).toContain('data-layout="horizontal"');
		expect(g.html).not.toContain('<svg');
		for (const s of ['Q1', 'in Q2', 'Q3']) expect(g.text).toContain(s);
	});

	it('a now rule only when now is inside the range', () => {
		const at = (now: number) => render(Timeline, { props: { timeline: { items: spans }, now } }).body;
		expect(at(Date.parse('2026-10-07'))).toMatch(/<line[^>]*class="now/);
		expect(at(Date.parse('2026-11-07'))).not.toMatch(/class="now/);
	});
});
