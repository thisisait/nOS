// Tree and timeline (renderers.rs): every label is a text node. One root with
// 2-4 children is an org chart; anything else is a nested list. A timeline is
// horizontal up to 6 items and vertical beyond. hi is a word, not only a colour.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Component from './Component.svelte';

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
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

	it('a timeline of at most 6 is horizontal, and hi is a word', () => {
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
		expect(g.html).toContain('data-layout="horizontal"');
	});

	it('a timeline past 6 items is vertical', () => {
		const items = Array.from({ length: 7 }, (_, i) => ({ when: `d${i}`, title: `t${i}` }));
		const g = draw({ kind: 'timeline', props: { items } });
		expect(g.text).toContain('t6');
		expect(g.html).toContain('data-layout="vertical"');
	});
});
