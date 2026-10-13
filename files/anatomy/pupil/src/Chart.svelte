<!--
  A chart the model shows (renderers.rs Chart): bar or line as inline SVG, no library.
  Every value is a mark with a <title> saying series, x and value; every label is a
  text node placed inside the 320x160 box (gate: fixture.test.ts "a chart is SVG marks").
-->
<script lang="ts">
	import type { Component } from './wire';

	let { chart }: { chart: Extract<Component, { kind: 'chart' }>['props'] } = $props();

	const W = 320, H = 160, T = 10, B = 18, GAP = 3;
	const FONT = 8, GLYPH = FONT * 0.6; // the widest UI glyph, so a label's width is bounded
	const COLOURS = ['--accent', '--warn', '--ok', '--bad', '--info', '--muted'].map((c) => `var(${c})`);
	const r1 = (n: number) => Math.round(n * 10) / 10;
	// At most 8 glyphs, so a y label fits left of the axis.
	const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
	const fmt = (v: number) => (compact.format(v).length <= 7 ? compact.format(v) : v.toExponential(1));
	const clip = (s: string, n: number) => (s.length <= n ? s : s.slice(0, Math.max(n - 1, 0)) + '…');

	const g = $derived.by(() => {
		const xs = [...new Set(chart.series.flatMap((s) => s.points.map(([x]) => x)))];
		const vals = chart.series.flatMap((s) => s.points.map(([, v]) => v));
		const lo = Math.min(0, ...vals);
		const hi = Math.max(0, ...vals) === lo ? lo + 1 : Math.max(0, ...vals);
		const yVals = [...new Set([lo, 0, hi])];
		// The gutter is the y labels, so the plot uses the rest of the box.
		const L = r1(Math.max(...yVals.map((v) => fmt(v).length * GLYPH)) + GAP);
		const R = GAP;
		const y = (v: number) => r1(H - B - ((v - lo) / (hi - lo)) * (H - B - T));
		const bw = (W - R - L) / Math.max(xs.length, 1);
		const cx = (i: number) => r1(L + bw * (i + 0.5));
		const step = Math.ceil(xs.length / 8);
		const room = Math.max(Math.floor((bw * step) / GLYPH), 1);
		const xLabels = xs.flatMap((x, i) => {
			if (i % step) return [];
			const t = clip(x, room), half = (t.length * GLYPH) / 2;
			return [{ t, x: r1(Math.min(Math.max(cx(i), half), W - half)) }];
		});
		const yLabels = yVals.map((v) => ({ t: fmt(v), y: r1(y(v) + FONT / 3) }));
		const n = chart.series.length, w = (bw * 0.8) / n;
		const marks = chart.series.map((s, k) => ({
			name: s.name,
			colour: COLOURS[k % COLOURS.length],
			points: s.points.map(([x, v]) => {
				const i = xs.indexOf(x);
				return { x, v, i, cx: cx(i), cy: y(v), bx: r1(L + bw * i + bw * 0.1 + k * w), top: Math.min(y(v), y(0)), h: r1(Math.max(Math.abs(y(v) - y(0)), 0.5)) };
			}),
		}));
		return { w: r1(w), base: y(0), xLabels, yLabels, marks, L, R };
	});
</script>

<svg viewBox="0 0 {W} {H}" role="img" aria-label="{chart.title ?? ''} {chart.chart} chart">
	<title>{chart.title ? `${chart.title} — ` : ''}{chart.chart} chart</title>
	<line class="axis" x1={g.L} y1={g.base} x2={W - g.R} y2={g.base} />
	{#each g.yLabels as l}<text x={g.L - 3} y={l.y} text-anchor="end" font-size={FONT}>{l.t}</text>{/each}
	{#each g.xLabels as l}<text x={l.x} y={H - 6} text-anchor="middle" font-size={FONT}>{l.t}</text>{/each}
	{#each g.marks as m}
		{#if chart.chart === 'bar'}
			{#each m.points as p}
				<rect class="bar" x={p.bx} y={p.top} width={g.w} height={p.h} style:fill={m.colour}><title>{m.name} · {p.x}: {p.v}</title></rect>
			{/each}
		{:else}
			<polyline points={m.points.map((p) => `${p.cx},${p.cy}`).join(' ')} style:stroke={m.colour} />
			{#each m.points as p}
				<circle cx={p.cx} cy={p.cy} r="1.5" style:fill={m.colour}><title>{m.name} · {p.x}: {p.v}</title></circle>
			{/each}
		{/if}
	{/each}
</svg>
<ul class="legend">
	{#each g.marks as m}<li><span class="swatch" style:background={m.colour}></span>{m.name}</li>{/each}
</ul>

<style>
	svg {
		width: 100%;
		max-width: 640px;
		display: block;
		color: var(--muted);
	}
	text {
		fill: var(--muted);
		font-family: ui-sans-serif, system-ui, sans-serif;
	}
	.axis {
		stroke: var(--glass-brd);
	}
	polyline {
		fill: none;
		stroke-width: 1.5;
	}
	.legend {
		list-style: none;
		padding: 0;
		margin: 4px 0 0;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		font-size: 11px;
	}
	.swatch {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 2px;
		margin-right: 4px;
	}
</style>
