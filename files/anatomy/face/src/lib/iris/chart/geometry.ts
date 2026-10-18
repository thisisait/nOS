// A chart's props -> every mark and label in a W x W/2 box. Pure, so node tests reach it.
import type { Component } from '../wire';
import { band, linear, ticks, timeTicks, type Tick } from './scale';
import { arcPath, areaPath, pieAngles, stack, type Pt } from './shape';
import { day, LOCALE } from '../fmt';
import { tip } from './tooltip';
import type { Zoom } from './zoom';

type Chart = Extract<Component, { kind: 'chart' }>['props'];

export type Mark = {
	id: string;
	tip: string;
	colour: string;
	/** a bar */
	rx?: number;
	ry?: number;
	rw?: number;
	rh?: number;
	/** a point */
	cx?: number;
	cy?: number;
	/** a slice */
	d?: string;
};
export type Drawn = { name: string; colour: string; marks: Mark[]; line?: string; area?: string };
export type Layout = {
	W: number;
	H: number;
	L: number;
	R: number;
	T: number;
	B: number;
	FONT: number;
	base: number;
	xLabels: { t: string; x: number }[];
	yLabels: { t: string; y: number }[];
	series: Drawn[];
	legend: { name: string; colour: string }[];
	zoomable: boolean;
	empty: boolean;
};

export const FONT = 8,
	GLYPH = FONT * 0.6; // the widest UI glyph, so a label's width is bounded
const T = 10,
	B = 18,
	GAP = 3;
const COLOURS = ['--accent', '--warn', '--ok', '--bad', '--info', '--muted'].map(
	(c) => `var(${c})`
);
const r1 = (n: number) => Math.round(n * 10) / 10;
// At most 9 glyphs ("12,3 tis."), so a y label fits left of the axis; a decimal goes before the exponent does.
export const fmt = (v: number, locale = LOCALE) => {
	const at = (d: number) =>
		new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: d }).format(v);
	return [at(1), at(0)].find((t) => t.length <= 9) ?? v.toExponential(1);
};
const clip = (s: string, n: number) => (s.length <= n ? s : s.slice(0, Math.max(n - 1, 0)) + '…');

/** Lines, areas and scatters zoom along x; a bar's x is its band and a pie has none. */
export const zooms = (c: Chart) =>
	c.chart === 'line' || c.chart === 'area' || c.chart === 'scatter';

export function layout(chart: Chart, W: number, zoom: Zoom, locale = LOCALE): Layout {
	const H = r1(W / 2);
	const pts = chart.series.flatMap((s) => s.points);
	const empty = pts.length === 0;
	const colourOf = (k: number) => COLOURS[k % COLOURS.length];
	const legend =
		chart.chart === 'pie'
			? (chart.series[0]?.points ?? []).map(([x], i) => ({ name: x, colour: colourOf(i) }))
			: chart.series.map((s, k) => ({ name: s.name, colour: colourOf(k) }));
	const out = {
		W,
		H,
		T,
		B,
		FONT,
		legend,
		zoomable: zooms(chart),
		empty,
		xLabels: [],
		yLabels: [],
		series: [],
		base: H - B,
		L: GAP,
		R: GAP
	};
	if (empty) return out;

	if (chart.chart === 'pie') {
		const s = chart.series[0];
		const r = (H - 2 * T) / 2,
			cx = W / 2,
			cy = H / 2;
		const angles = pieAngles(s.points.map(([, v]) => v));
		const marks = s.points.map(([x, v], i) => ({
			id: `0:${i}`,
			tip: tip(s.name, x, v, locale),
			colour: colourOf(i),
			d: arcPath(r1(cx), r1(cy), r1(r), ...angles[i])
		}));
		return { ...out, series: [{ name: s.name, colour: colourOf(0), marks }] };
	}

	// x: a number or a time is placed by its value; a category (and every bar) by its order.
	const value = chart.x === 'time' ? (x: string) => Date.parse(x) : (x: string) => Number(x);
	const byValue = chart.x !== 'category';
	const xs = [...new Set(pts.map(([x]) => x))];
	if (byValue) xs.sort((a, b) => value(a) - value(b));
	const stacked = chart.chart === 'stacked_bar';
	const ranges = stacked
		? stack(chart.series.map((s) => xs.map((x) => s.points.find((p) => p[0] === x)?.[1] ?? 0)))
		: null;
	const vals = ranges ? ranges.flat(2) : pts.map(([, v]) => v);
	const lo = Math.min(0, ...vals);
	const hi = Math.max(0, ...vals) === lo ? lo + 1 : Math.max(0, ...vals);
	const yVals = [...new Set([lo, 0, hi])];
	// The gutter is the y labels, so the plot uses the rest of the box.
	const L = r1(Math.max(...yVals.map((v) => fmt(v, locale).length * GLYPH)) + GAP);
	const R = GAP,
		pw = W - R - L;
	const y = linear(lo, hi, H - B, T);
	const yr = (v: number) => r1(y(v));

	const bars = chart.chart === 'bar' || stacked;
	const z = zooms(chart) ? zoom : { k: 1, tx: 0, ty: 0 };
	const bnd = band(xs.length, 0, pw);
	const vs = xs.map(value);
	const [d0, d1] = [Math.min(...vs), Math.max(...vs)];
	const PAD = 4; // a point on the domain's edge keeps its circle off the axis
	const world = byValue && !bars ? linear(d0, d1, PAD, pw - PAD) : null;
	const sx = (u: number) => L + u * z.k + z.tx;
	const at = (x: string) => r1(sx(world ? world(value(x)) : bnd.mid(xs.indexOf(x))));
	const inPlot = (px: number) => px >= L - 0.05 && px <= W - R + 0.05;

	// x labels: a category every `step`th, clipped to its room; a value axis gets nice ticks over what is in view.
	let xLabels: { t: string; x: number }[];
	const place = (t: string, px: number) => {
		const half = (t.length * GLYPH) / 2;
		return { t, x: r1(Math.min(Math.max(px, half), W - half)) };
	};
	if (world) {
		const inv = linear(PAD, pw - PAD, d0, d1);
		const [v0, v1] = [inv((0 - z.tx) / z.k), inv((pw - z.tx) / z.k)];
		const n = Math.max(2, Math.floor(pw / 60));
		const tk: Tick[] =
			chart.x === 'time'
				? timeTicks(v0, v1, n)
				: ticks(v0, v1, n).map((v) => ({ v, label: fmt(v, locale) }));
		xLabels = tk
			.map((t) => ({ t: t.label, px: L + world(t.v) * z.k + z.tx }))
			.filter((t) => inPlot(t.px))
			.map((t) => place(t.t, t.px));
	} else {
		const step = Math.ceil(xs.length / (8 * z.k));
		const room = Math.max(Math.floor((bnd.step * z.k * step) / GLYPH), 1);
		xLabels = xs.flatMap((x, i) =>
			i % step || !inPlot(at(x)) ? [] : [place(clip(day(x, locale) ?? x, room), at(x))]
		);
	}
	const yLabels = yVals.map((v) => ({ t: fmt(v, locale), y: r1(y(v) + FONT / 3) }));

	const n = chart.series.length;
	const bw = bnd.step * 0.8,
		w = stacked ? bw : bw / n;
	const series: Drawn[] = chart.series.map((s, k) => {
		const colour = colourOf(k);
		const marks: Mark[] = s.points.flatMap<Mark>(([x, v], i) => {
			const id = `${k}:${i}`,
				t = tip(s.name, x, v, locale);
			if (bars) {
				const j = xs.indexOf(x);
				const [b0, b1] = ranges ? ranges[k][j] : [Math.min(v, 0), Math.max(v, 0)];
				const top = yr(b1),
					bottom = yr(b0);
				const h = ranges ? bottom - top : Math.max(bottom - top, 0.5);
				return [
					{
						id,
						tip: t,
						colour,
						rx: r1(L + bnd.at(j) + bnd.step * 0.1 + (stacked ? 0 : k * w)),
						ry: ranges ? top : Math.min(top, bottom),
						rw: r1(w),
						rh: r1(h)
					}
				];
			}
			const cx = at(x);
			return inPlot(cx) ? [{ id, tip: t, colour, cx, cy: yr(v) }] : [];
		});
		if (bars || chart.chart === 'scatter') return { name: s.name, colour, marks };
		const sorted = byValue ? [...s.points].sort((a, b) => value(a[0]) - value(b[0])) : s.points;
		const line: Pt[] = sorted.map(([x, v]) => [at(x), yr(v)]);
		const drawn: Drawn = {
			name: s.name,
			colour,
			marks,
			line: line.map((p) => p.join(',')).join(' ')
		};
		if (chart.chart === 'area')
			drawn.area = areaPath(
				line,
				line.map(([px]) => [px, yr(0)])
			);
		return drawn;
	});
	return { ...out, L, R, base: yr(0), xLabels, yLabels, series };
}
