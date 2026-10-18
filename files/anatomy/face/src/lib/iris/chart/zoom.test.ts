import { describe, expect, it } from 'vitest';
import { IDENTITY, drag, key, wheel, zoomAt, type Box } from './zoom';

const box: Box = { w: 200, h: 100 };
const world = (z: { k: number; tx: number; ty: number }, [x, y]: [number, number]) => [
	(x - z.tx) / z.k,
	(y - z.ty) / z.k
];

describe('zoom and pan', () => {
	it('a wheel at a point keeps that point fixed', () => {
		const z = wheel(IDENTITY, [50, 40], -300, box);
		expect(z.k).toBe(2);
		expect(world(z, [50, 40])).toEqual([50, 40]);
		const z2 = wheel(z, [120, 60], -150, box);
		const [a, b] = world(z, [120, 60]);
		const [c, d] = world(z2, [120, 60]);
		expect(c).toBeCloseTo(a);
		expect(d).toBeCloseTo(b);
	});

	it('+, - and 0 are the same zoom as the wheel at the centre, and reset', () => {
		expect(key(IDENTITY, '+', box)).toEqual(zoomAt(IDENTITY, [100, 50], 1.5, box));
		expect(key(IDENTITY, '=', box)).toEqual(key(IDENTITY, '+', box));
		const z = key(IDENTITY, '+', box)!;
		expect(key(z, '-', box)!.k).toBeCloseTo(1);
		expect(key(z, '0', box)).toEqual(IDENTITY);
		expect(key(z, 'a', box)).toBeNull();
	});

	it('the view is clamped: never out past 1, never in past the cap, never panned off the content', () => {
		expect(wheel(IDENTITY, [10, 10], 500, box)).toEqual(IDENTITY);
		expect(wheel(IDENTITY, [10, 10], -1e6, box).k).toBe(20);
		const z = zoomAt(IDENTITY, [100, 50], 2, box);
		expect(drag(z, 1000, 1000, box)).toEqual({ k: 2, tx: 0, ty: 0 });
		expect(drag(z, -1000, -1000, box)).toEqual({ k: 2, tx: -200, ty: -100 });
		expect(drag(IDENTITY, 30, 30, box)).toEqual(IDENTITY);
	});

	it('an x-only box never moves y', () => {
		const xOnly = { ...box, xOnly: true };
		const z = wheel(IDENTITY, [50, 40], -300, xOnly);
		expect(z.ty).toBe(0);
		expect(drag(z, -10, -10, xOnly)).toEqual({ k: 2, tx: z.tx - 10, ty: 0 });
	});
});
