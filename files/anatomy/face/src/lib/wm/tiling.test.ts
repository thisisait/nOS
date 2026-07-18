import { describe, it, expect } from 'vitest';
import { prefix, moveBoundary, cellRect, MIN_TRACK, MENUBAR } from './tiling';

describe('tiling · prefix', () => {
	it('cumulative track starts, dropping nothing', () => {
		expect(prefix([0.5, 0.5])).toEqual([0, 0.5]);
		expect(prefix([1 / 3, 1 / 3, 1 / 3])).toEqual([0, 1 / 3, 2 / 3]);
		expect(prefix([1])).toEqual([0]);
	});
});

describe('tiling · moveBoundary', () => {
	it('re-allocates the pair, preserving their combined span', () => {
		const next = moveBoundary([0.5, 0.5], 0, 0.7);
		expect(next[0]).toBeCloseTo(0.7);
		expect(next[1]).toBeCloseTo(0.3);
		expect(next[0] + next[1]).toBeCloseTo(1);
	});
	it('clamps so neither track drops below MIN_TRACK', () => {
		const tiny = moveBoundary([0.5, 0.5], 0, 0.99);
		expect(tiny[0]).toBeCloseTo(1 - MIN_TRACK);
		expect(tiny[1]).toBeCloseTo(MIN_TRACK);
		const tiny2 = moveBoundary([0.5, 0.5], 0, 0.01);
		expect(tiny2[0]).toBeCloseTo(MIN_TRACK);
	});
	it('only touches the two adjacent tracks in a 3-col grid', () => {
		const next = moveBoundary([1 / 3, 1 / 3, 1 / 3], 1, 0.8);
		expect(next[0]).toBeCloseTo(1 / 3); // untouched
		expect(next[1] + next[2]).toBeCloseTo(2 / 3);
		expect(next[1]).toBeCloseTo(0.8 - 1 / 3);
	});
	it('is a no-op for an out-of-range boundary', () => {
		expect(moveBoundary([1], 0, 0.5)).toEqual([1]);
	});
});

describe('tiling · cellRect', () => {
	const area = { w: 1000, h: 900 };
	it('maps a 2×2 grid cell to pixels below the menubar', () => {
		// bottom-right cell of a 0.5/0.5 grid
		expect(cellRect([0.5, 0.5], [0.5, 0.5], 1, 1, area)).toEqual({
			x: 500,
			y: MENUBAR + 450,
			w: 500,
			h: 450
		});
	});
	it('honours asymmetric column fractions', () => {
		const r = cellRect([0.7, 0.3], [1], 1, 0, area);
		expect(r.x).toBe(700);
		expect(r.w).toBe(300);
		expect(r.y).toBe(MENUBAR);
		expect(r.h).toBe(900);
	});
});
