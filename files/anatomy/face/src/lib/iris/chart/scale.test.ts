import { describe, expect, it } from 'vitest';
import { band, linear, niceStep, ticks, timeTicks } from './scale';

describe('scales', () => {
	it('a nice step is 1, 2 or 5 times a power of ten', () => {
		expect(niceStep(95, 5)).toBe(20);
		expect(niceStep(1, 5)).toBe(0.2);
		expect(niceStep(7000, 4)).toBe(2000);
		expect(niceStep(0.03, 3)).toBe(0.01);
	});

	it('ticks fall on the step, inside the domain, with no float dust', () => {
		expect(ticks(0, 95, 5)).toEqual([0, 20, 40, 60, 80]);
		expect(ticks(-1, 1, 4)).toEqual([-1, -0.5, 0, 0.5, 1]);
		expect(ticks(0.1, 0.3, 2)).toEqual([0.1, 0.2, 0.3]);
		expect(ticks(5, 5, 5)).toEqual([5]);
	});

	it('linear maps the domain onto the range, either way round', () => {
		const y = linear(0, 100, 150, 10);
		expect([y(0), y(50), y(100)]).toEqual([150, 80, 10]);
		expect(linear(3, 3, 0, 10)(3)).toBe(5);
	});

	it('time ticks step by hours, days, months or years and say it in that unit', () => {
		const t = (s: string) => Date.parse(s);
		expect(timeTicks(t('2026-10-13T00:00:00Z'), t('2026-10-13T12:00:00Z'), 4).map((x) => x.label)).toEqual(['00:00', '03:00', '06:00', '09:00', '12:00']);
		expect(timeTicks(t('2026-10-01'), t('2026-10-05'), 4).map((x) => x.label)).toEqual(['10-01', '10-02', '10-03', '10-04', '10-05']);
		expect(timeTicks(t('2026-01-15'), t('2026-06-15'), 5).map((x) => x.label)).toEqual(['2026-02', '2026-03', '2026-04', '2026-05', '2026-06']);
		expect(timeTicks(t('2019-06-01'), t('2026-06-01'), 4).map((x) => x.label)).toEqual(['2020', '2022', '2024', '2026']);
		for (const x of timeTicks(t('2026-01-15'), t('2026-06-15'), 5)) expect(new Date(x.v).getUTCDate()).toBe(1);
	});

	it('a band splits the range into equal steps, mid on each centre', () => {
		const b = band(4, 20, 100);
		expect(b.step).toBe(20);
		expect([b.at(0), b.mid(0), b.mid(3)]).toEqual([20, 30, 90]);
	});
});
