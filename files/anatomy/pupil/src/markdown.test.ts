import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Markdown from './Markdown.svelte';
import { inline, parse } from './markdown';

// An <ol> with no value numbers from 1. The digits in the source are the
// numbers the person wrote; the tree and each <li value> must keep them.
describe('an ordered list keeps the numbers in the source', () => {
	it('3. 4. and 9) stay 3, 4 and 9, not 1, 2 and 3', () => {
		const src = '3. three\n4. four\n9) nine';
		const html = render(Markdown, { props: { text: src } }).body;
		const values = [...html.matchAll(/<li[^>]*\bvalue="(\d+)"/g)].map((m) => m[1]);
		expect(values).toEqual(['3', '4', '9']);
		expect(parse(src)).toEqual([
			{
				t: 'ol',
				items: [
					{ n: 3, inl: [{ t: 'text', text: 'three' }] },
					{ n: 4, inl: [{ t: 'text', text: 'four' }] },
					{ n: 9, inl: [{ t: 'text', text: 'nine' }] },
				],
			},
		]);
	});
});

// The inline regex re-read the suffix from every unclosed "[" (the label class
// included "["): 32000 of them took ~600 ms. A linear scan is far under the bound.
describe('unclosed inline markers do not backtrack', () => {
	it('a long unclosed [, ** or * is literal text, quickly', () => {
		const n = 32000;
		const cases: [string, string][] = [
			['[', '['.repeat(n)],
			['**', '**' + 'a'.repeat(n)],
			['*', '*' + 'a'.repeat(n)],
		];
		for (const [name, s] of cases) {
			const t0 = performance.now();
			const got = inline(s);
			const ms = performance.now() - t0;
			expect(ms, name).toBeLessThan(100);
			expect(got, name).toEqual([{ t: 'text', text: s }]);
		}
	});
});

// A "  - " under an item is a child list. The marker regex used to eat the indent,
// so the child was another top-level item.
describe('an indented dash is a second list level', () => {
	const drawn = (src: string) =>
		render(Markdown, { props: { text: src } }).body.replace(/<!--[\s\S]*?-->/g, '').replace(/ class="[^"]*"/g, '');

	it('a "  - " under an item is nested, and the next "-" is not', () => {
		const src = '- parent\n  - child\n- next';
		expect(drawn(src)).toContain('<ul><li>parent<ul><li>child</li></ul></li><li>next</li></ul>');
		expect(parse(src)).toEqual([
			{
				t: 'ul',
				items: [
					{ inl: [{ t: 'text', text: 'parent' }], sub: [[{ t: 'text', text: 'child' }]] },
					{ inl: [{ t: 'text', text: 'next' }], sub: [] },
				],
			},
		]);
	});
});

// An image is words. The url is not drawn and nothing is fetched.
describe('an image is words, not a link', () => {
	it('![alt](url) is [obrázek: alt], with no url and no img', () => {
		const src = 'see ![plot](https://example.com/a.png) now';
		const html = render(Markdown, { props: { text: src } }).body;
		expect(html).toContain('[obrázek: plot]');
		expect(html).not.toContain('example.com');
		expect(html).not.toContain('<img');
		expect(html).not.toContain('!plot');
		expect(parse(src)).toEqual([
			{
				t: 'p',
				inl: [
					{ t: 'text', text: 'see ' },
					{ t: 'text', text: '[obrázek: plot]' },
					{ t: 'text', text: ' now' },
				],
			},
		]);
		expect(inline('[docs](https://thisisait.eu)')).toEqual([
			{ t: 'link', text: 'docs', url: 'https://thisisait.eu' },
		]);
	});
});

// Live 2026-10-13: a model's `---` divider was drawn as three dashes.
describe('a thematic break', () => {
	it('--- between paragraphs is a rule, not text', () => {
		expect(parse('a\n---\nb')).toEqual([
			{ t: 'p', inl: [{ t: 'text', text: 'a' }] }, { t: 'hr' }, { t: 'p', inl: [{ t: 'text', text: 'b' }] }]);
	});
});
