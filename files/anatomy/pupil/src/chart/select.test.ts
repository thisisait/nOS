import { describe, expect, it } from 'vitest';
import { dimmed, toggle } from './select';
import { tip } from './tooltip';

describe('selection and the mark text', () => {
	it('select toggles a mark in and out, and dims the rest only while any is selected', () => {
		const one = toggle([], '0:1');
		expect(one).toEqual(['0:1']);
		expect(toggle(toggle(one, '1:0'), '0:1')).toEqual(['1:0']);
		expect(toggle(one, '0:1')).toEqual([]);
		expect(dimmed([], '0:0')).toBe(false);
		expect(dimmed(one, '0:0')).toBe(true);
		expect(dimmed(one, '0:1')).toBe(false);
	});

	it('a tooltip is series · x: y', () => {
		expect(tip('roadmap', 'done', 95)).toBe('roadmap · done: 95');
		expect(tip('p50', '3', -1.5)).toBe('p50 · 3: -1.5');
	});
});
