import { describe, expect, it } from 'vitest';
import type { Component } from '../wire';
import { layout } from './geometry';
import { IDENTITY } from './zoom';

type Chart = Extract<Component, { kind: 'chart' }>['props'];
const xs = (c: Chart) => layout(c, 320, IDENTITY).series[0].marks.map((m) => m.cx!);

describe('geometry', () => {
	it('a number x is placed by its value, not its order', () => {
		const [a, b, c] = xs({ chart: 'scatter', x: 'number', series: [{ name: 's', points: [['0', 1], ['10', 2], ['1', 3]] }] });
		expect((c - a) / (b - a)).toBeCloseTo(0.1);
	});

	it('a time x is placed by its instant', () => {
		const [a, b, c] = xs({ chart: 'line', x: 'time', series: [{ name: 's', points: [['2026-10-01', 1], ['2026-10-02', 2], ['2026-10-11', 3]] }] });
		expect((c - a) / (b - a)).toBeCloseTo(10, 0);
	});

	it('a stacked bar sits on the one below it', () => {
		const g = layout({ chart: 'stacked_bar', x: 'category', series: [
			{ name: 'a', points: [['x', 2]] }, { name: 'b', points: [['x', 3]] }] }, 320, IDENTITY);
		const [lo, hi] = [g.series[0].marks[0], g.series[1].marks[0]];
		expect(hi.ry! + hi.rh!).toBeCloseTo(lo.ry!);
		expect(hi.rx).toBe(lo.rx);
	});

	it('the box keeps its aspect as it widens', () => {
		const c: Chart = { chart: 'bar', x: 'category', series: [{ name: 's', points: [['x', 1]] }] };
		expect([layout(c, 320, IDENTITY).H, layout(c, 640, IDENTITY).H]).toEqual([160, 320]);
	});

	it('zooming a line spreads its points; a bar or a pie does not zoom', () => {
		const line: Chart = { chart: 'line', x: 'number', series: [{ name: 's', points: [['0', 1], ['1', 2]] }] };
		const g = layout(line, 320, IDENTITY);
		const far = layout(line, 320, { k: 2, tx: 0, ty: 0 }).series[0].marks;
		expect(g.zoomable).toBe(true);
		expect(far.length, 'the second point is past the right edge').toBe(1);
		expect(far[0].cx! - g.L).toBeCloseTo(2 * (g.series[0].marks[0].cx! - g.L), 0);
		expect(layout({ ...line, chart: 'bar' }, 320, IDENTITY).zoomable).toBe(false);
		expect(layout({ ...line, chart: 'pie' }, 320, IDENTITY).zoomable).toBe(false);
	});

	it('no points is said empty', () => {
		expect(layout({ chart: 'bar', x: 'category', series: [{ name: 'rows', points: [] }] }, 320, IDENTITY).empty).toBe(true);
	});
});
