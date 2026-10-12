import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Markdown from './Markdown.svelte';
import { parse } from './markdown';

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
