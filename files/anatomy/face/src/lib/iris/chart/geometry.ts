// A chart's props -> every mark and label in a W x W/2 box. Pure, so node tests reach it.
import type { Component } from '../wire';
import { band, linear, ticks, timeTicks, type Tick } from './scale';
import { arcPath, areaPath, linePath, pieAngles, ringPath, stack, type Pt } from './shape';
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
	/** a radar's and a radial's own labels, placed where they belong */
	labels: { t: string; x: number; y: number; anchor: 'start' | 'middle' | 'end' }[];
	/** a radar's rings and spokes */
	grid?: string;
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
		chart.chart === 'pie' || chart.chart === 'radial'
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
		labels: [],
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

	if (chart.chart === 'radar') return { ...out, ...radar(chart, W, H, colourOf, locale) };
	if (chart.chart === 'radial') return { ...out, ...radial(chart, W, H, colourOf, locale) };
	if (chart.chart === 'horizontal_bar')
		return { ...out, ...horizontal(chart, W, H, colourOf, locale) };

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

type Colour = (k: number) => string;

/** One closed shape per series over spokes (every series has the same x, renderers.rs), 3 rings of the scale. */
function radar(chart: Chart, W: number, H: number, colourOf: Colour, locale: string) {
	const xs = chart.series[0].points.map(([x]) => x);
	const cx = W / 2,
		cy = H / 2,
		R = (H - 2 * T) / 2 - FONT / 2;
	const hi = Math.max(0, ...chart.series.flatMap((s) => s.points.map(([, v]) => v))) || 1;
	const ang = (i: number) => (i / xs.length) * 2 * Math.PI;
	const pt = (i: number, r: number): Pt => [
		r1(cx + r * Math.sin(ang(i))),
		r1(cy - r * Math.cos(ang(i)))
	];
	const ring = (r: number) => linePath(xs.map((_, i) => pt(i, r))) + 'Z';
	const grid =
		[1 / 3, 2 / 3, 1].map((f) => ring(R * f)).join('') +
		xs.map((_, i) => `M${r1(cx)},${r1(cy)}L${pt(i, R).join(',')}`).join('');
	const labels: Layout['labels'] = xs.map((x, i) => {
		const sin = Math.sin(ang(i));
		const anchor = sin > 0.1 ? 'start' : sin < -0.1 ? 'end' : 'middle';
		const [lx, ly] = pt(i, R + 4);
		const room = anchor === 'start' ? W - lx : anchor === 'end' ? lx : 2 * Math.min(lx, W - lx);
		return {
			t: clip(day(x, locale) ?? x, Math.floor(room / GLYPH)),
			x: lx,
			y: r1(ly + FONT / 3),
			anchor
		};
	});
	labels.push({ t: fmt(hi, locale), x: r1(cx + 2), y: r1(cy - R + FONT), anchor: 'start' });
	const series: Drawn[] = chart.series.map((s, k) => {
		const colour = colourOf(k);
		const at = s.points.map(([, v], i) => pt(i, (R * v) / hi));
		const marks = s.points.map(([x, v], i) => ({
			id: `${k}:${i}`,
			tip: tip(s.name, x, v, locale),
			colour,
			cx: at[i][0],
			cy: at[i][1]
		}));
		return { name: s.name, colour, marks, area: linePath(at) + 'Z' };
	});
	return { labels, grid, series };
}

/** One series as concentric rings, outermost first; the largest value spans three quarters of a turn. */
function radial(chart: Chart, W: number, H: number, colourOf: Colour, locale: string) {
	const s = chart.series[0];
	const cx = W / 2,
		cy = H / 2,
		R = (H - 2 * T) / 2,
		w = (R * 0.75) / s.points.length;
	const hi = Math.max(0, ...s.points.map(([, v]) => v)) || 1;
	const marks = s.points.map(([x, v], i) => ({
		id: `0:${i}`,
		tip: tip(s.name, x, v, locale),
		colour: colourOf(i),
		d: ringPath(r1(cx), r1(cy), r1(R - i * w - w * 0.8), r1(R - i * w), 0, (v / hi) * 1.5 * Math.PI)
	}));
	// The empty quarter left of 12 o'clock holds each ring's name, when a ring is tall enough for a line.
	const labels: Layout['labels'] =
		w < FONT
			? []
			: s.points.map(([x], i) => ({
					t: clip(day(x, locale) ?? x, Math.floor((cx - 3) / GLYPH)),
					x: r1(cx - 3),
					y: r1(cy - (R - i * w - w * 0.4) + FONT / 3),
					anchor: 'end' as const
				}));
	return { labels, series: [{ name: s.name, colour: colourOf(0), marks }] };
}

/** Bars along x from 0, one band per label down the side; a number x is placed in its order. */
function horizontal(chart: Chart, W: number, H: number, colourOf: Colour, locale: string) {
	const pts = chart.series.flatMap((s) => s.points);
	const xs = [...new Set(pts.map(([x]) => x))];
	if (chart.x === 'number') xs.sort((a, b) => Number(a) - Number(b));
	const vals = pts.map(([, v]) => v);
	const lo = Math.min(0, ...vals);
	const hi = Math.max(0, ...vals) === lo ? lo + 1 : Math.max(0, ...vals);
	const name = (x: string) => day(x, locale) ?? x;
	const L = r1(Math.min(Math.max(...xs.map((x) => name(x).length)), 24) * GLYPH + 2 * GAP);
	const R = GAP;
	const x = linear(lo, hi, L, W - R);
	const bnd = band(xs.length, T, H - B);
	const step = Math.ceil((xs.length * FONT * 1.2) / (H - B - T));
	const room = Math.max(Math.floor((L - 2 * GAP) / GLYPH), 1);
	const yLabels = xs.flatMap((t, j) =>
		j % step ? [] : [{ t: clip(name(t), room), y: r1(bnd.mid(j) + FONT / 3) }]
	);
	const xLabels = [...new Set([lo, 0, hi])].map((v) => {
		const t = fmt(v, locale),
			half = (t.length * GLYPH) / 2;
		return { t, x: r1(Math.min(Math.max(x(v), half), W - half)) };
	});
	const h = (bnd.step * 0.8) / chart.series.length;
	const series: Drawn[] = chart.series.map((s, k) => {
		const colour = colourOf(k);
		const marks = s.points.map(([t, v], i) => {
			const [a, b] = [x(Math.min(v, 0)), x(Math.max(v, 0))];
			return {
				id: `${k}:${i}`,
				tip: tip(s.name, t, v, locale),
				colour,
				rx: r1(a),
				ry: r1(bnd.at(xs.indexOf(t)) + bnd.step * 0.1 + k * h),
				rw: r1(Math.max(b - a, 0.5)),
				rh: r1(h)
			};
		});
		return { name: s.name, colour, marks };
	});
	return { L, R, base: H - B, xLabels, yLabels, series };
}
