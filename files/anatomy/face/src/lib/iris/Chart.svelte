<!--
  A chart the model shows (renderers.rs Chart) as inline SVG, no library: the marks and labels
  come from chart/geometry.ts. Every value is a focusable mark with a <title> (series · x: value);
  every label is a text node inside the viewBox, which follows the container's width at a fixed
  aspect (gate: fixture.test.ts "a chart is SVG marks"). Lines, areas and scatters zoom along x.
-->
<script lang="ts">
	import type { Component } from './wire';
	import { layout } from './chart/geometry';
	import { dimmed, toggle } from './chart/select';
	import { IDENTITY, drag, key, wheel, type Zoom } from './chart/zoom';

	let { chart }: { chart: Extract<Component, { kind: 'chart' }>['props'] } = $props();

	// One viewBox unit is 1.4 px once the container is wider than the 320-unit floor, so text keeps its size.
	const SCALE = 1.4;
	const clip = $props.id();
	let width = $state(0);
	let zoom: Zoom = $state(IDENTITY);
	let sel: string[] = $state([]);
	let focused = $state('');
	let svg: SVGSVGElement | undefined = $state();

	const g = $derived(layout(chart, Math.max(320, Math.round(width / SCALE)), zoom));
	const box = $derived({ w: g.W - g.L - g.R, h: g.H, xOnly: true });
	const marks = $derived(g.series.flatMap((s) => s.marks));
	const live = $derived(
		focused ||
			marks
				.filter((m) => sel.includes(m.id))
				.map((m) => m.tip)
				.join('; ')
	);
	const label = $derived(
		`${chart.title ? `${chart.title} — ` : ''}${chart.chart} chart, ${chart.x} x`
	);

	/** A client point as plot units, left edge of the plot = 0. */
	const plotPoint = (e: MouseEvent): [number, number] => {
		const r = svg!.getBoundingClientRect();
		const k = g.W / (r.width || g.W);
		return [(e.clientX - r.left) * k - g.L, (e.clientY - r.top) * k];
	};

	$effect(() => {
		const el = svg;
		if (!el || !g.zoomable) return;
		const on = (e: WheelEvent) => {
			e.preventDefault();
			zoom = wheel(zoom, plotPoint(e), e.deltaY, box);
		};
		el.addEventListener('wheel', on, { passive: false });
		return () => el.removeEventListener('wheel', on);
	});

	// Capture only once the pointer has moved: capturing on press would steal a mark's click.
	let press: { id: number; x: number; moved: boolean } | null = null;
	function down(e: PointerEvent) {
		if (g.zoomable && e.button === 0) press = { id: e.pointerId, x: plotPoint(e)[0], moved: false };
	}
	function move(e: PointerEvent) {
		if (!press || press.id !== e.pointerId) return;
		const [x] = plotPoint(e);
		if (!press.moved && Math.abs(x - press.x) < 3) return;
		if (!press.moved) svg?.setPointerCapture(e.pointerId);
		zoom = drag(zoom, x - press.x, 0, box);
		press = { ...press, x, moved: true };
	}
	function up(e: PointerEvent) {
		if (press?.moved && svg?.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
		press = null;
	}
	function keys(e: KeyboardEvent) {
		const z = g.zoomable ? key(zoom, e.key, box) : null;
		if (z) {
			zoom = z;
			e.preventDefault();
		}
	}
	function pick(id: string) {
		sel = toggle(sel, id);
	}
	function markKey(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			pick(id);
		}
	}
</script>

<div class="chart" bind:clientWidth={width}>
	{#if g.empty}
		<p class="empty">{label}: no rows yet</p>
	{:else}
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<svg
			bind:this={svg}
			viewBox="0 0 {g.W} {g.H}"
			role="group"
			aria-label={label}
			tabindex="0"
			onkeydown={keys}
			onpointerdown={down}
			onpointermove={move}
			onpointerup={up}
			onpointercancel={up}
		>
			<title>{label}</title>
			{#if g.zoomable}
				<defs
					><clipPath id={clip}><rect x={g.L} y="0" width={g.W - g.L - g.R} height={g.H} /></clipPath
					></defs
				>
			{/if}
			{#if chart.chart !== 'pie'}
				<line class="axis" x1={g.L} y1={g.base} x2={g.W - g.R} y2={g.base} />
				{#each g.yLabels as l}<text x={g.L - 3} y={l.y} text-anchor="end" font-size={g.FONT}
						>{l.t}</text
					>{/each}
				{#each g.xLabels as l}<text x={l.x} y={g.H - 6} text-anchor="middle" font-size={g.FONT}
						>{l.t}</text
					>{/each}
			{/if}
			<g clip-path={g.zoomable ? `url(#${clip})` : undefined}>
				{#each g.series as s}
					{#if s.area}<path
							class="area"
							d={s.area}
							style:fill={s.colour}
							style:stroke={s.colour}
						/>{/if}
					{#if s.line && !s.area}<polyline points={s.line} style:stroke={s.colour} />{/if}
					{#each s.marks as m (m.id)}
						{#if m.d !== undefined}
							<path
								class="slice mark"
								class:dim={dimmed(sel, m.id)}
								d={m.d}
								style:fill={m.colour}
								tabindex="0"
								role="button"
								aria-pressed={sel.includes(m.id)}
								onclick={() => pick(m.id)}
								onkeydown={(e) => markKey(e, m.id)}
								onfocus={() => (focused = m.tip)}
								onblur={() => (focused = '')}><title>{m.tip}</title></path
							>
						{:else if m.rx !== undefined}
							<rect
								class="bar mark"
								class:dim={dimmed(sel, m.id)}
								x={m.rx}
								y={m.ry}
								width={m.rw}
								height={m.rh}
								style:fill={m.colour}
								tabindex="0"
								role="button"
								aria-pressed={sel.includes(m.id)}
								onclick={() => pick(m.id)}
								onkeydown={(e) => markKey(e, m.id)}
								onfocus={() => (focused = m.tip)}
								onblur={() => (focused = '')}><title>{m.tip}</title></rect
							>
						{:else}
							<circle
								class="mark"
								class:dim={dimmed(sel, m.id)}
								cx={m.cx}
								cy={m.cy}
								r={chart.chart === 'scatter' ? 2.5 : 1.5}
								style:fill={m.colour}
								tabindex="0"
								role="button"
								aria-pressed={sel.includes(m.id)}
								onclick={() => pick(m.id)}
								onkeydown={(e) => markKey(e, m.id)}
								onfocus={() => (focused = m.tip)}
								onblur={() => (focused = '')}><title>{m.tip}</title></circle
							>
						{/if}
					{/each}
				{/each}
			</g>
		</svg>
	{/if}
	<p class="live" aria-live="polite">{live}</p>
	<div class="foot">
		<ul class="legend">
			{#each g.legend as m}<li>
					<span class="swatch" style:background={m.colour}></span>{m.name}
				</li>{/each}
		</ul>
		{#if g.zoomable && !g.empty}
			<button
				type="button"
				onclick={() => (zoom = IDENTITY)}
				disabled={zoom.k === 1 && zoom.tx === 0}>Reset zoom</button
			>
		{/if}
	</div>
</div>

<style>
	.chart {
		width: 100%;
	}
	svg {
		width: 100%;
		display: block;
		color: var(--muted);
		touch-action: pan-y;
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
	.area {
		fill-opacity: 0.25;
		stroke-width: 1.5;
	}
	.mark {
		cursor: pointer;
		transition: opacity 120ms;
	}
	.mark:focus-visible {
		outline: none;
		stroke: var(--accent);
		stroke-width: 1;
	}
	.dim {
		opacity: 0.3;
	}
	.live {
		min-height: 1.2em;
		margin: 2px 0 0;
		font-size: 11px;
		color: var(--muted);
	}
	.empty {
		color: var(--muted);
		font-style: italic;
	}
	.foot {
		display: flex;
		align-items: start;
		justify-content: space-between;
		gap: 8px;
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
	button {
		font-size: 11px;
	}
	@media (prefers-reduced-motion: reduce) {
		.mark {
			transition: none;
		}
	}
</style>
