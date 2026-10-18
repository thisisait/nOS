import { describe, expect, it } from 'vitest';
import { arcPath, areaPath, linePath, pieAngles, stack } from './shape';

describe('shapes', () => {
	it('a line is a move then a line per point', () => {
		expect(
			linePath([
				[0, 1],
				[2, 3],
				[4, 5]
			])
		).toBe('M0,1L2,3L4,5');
		expect(linePath([])).toBe('');
	});

	it('an area runs along the top and back along the base, closed', () => {
		expect(
			areaPath(
				[
					[0, 1],
					[2, 3]
				],
				[
					[0, 9],
					[2, 9]
				]
			)
		).toBe('M0,1L2,3L2,9L0,9Z');
	});

	it('a stack piles positives up and negatives down, per x', () => {
		expect(
			stack([
				[1, -2],
				[3, 4],
				[-1, -1]
			])
		).toEqual([
			[
				[0, 1],
				[-2, 0]
			],
			[
				[1, 4],
				[0, 4]
			],
			[
				[-1, 0],
				[-3, -2]
			]
		]);
	});

	it("a pie starts at 12 o'clock and its angles add up to a turn", () => {
		const a = pieAngles([1, 0, 3]);
		expect(a[0]).toEqual([0, Math.PI / 2]);
		expect(a[1]).toEqual([Math.PI / 2, Math.PI / 2]);
		expect(a[2][1]).toBeCloseTo(2 * Math.PI);
		expect(pieAngles([0, 0])).toEqual([
			[0, 0],
			[0, 0]
		]);
	});

	it('an arc is a wedge from the centre; a whole turn is two half arcs', () => {
		expect(arcPath(10, 10, 5, 0, Math.PI / 2)).toBe('M10,10L10,5A5,5 0 0 1 15,10Z');
		expect(arcPath(10, 10, 5, 0, 2 * Math.PI)).toBe('M10,5A5,5 0 1 1 10,15A5,5 0 1 1 10,5Z');
	});
});
