<!--
  A timeline the model shows (renderers.rs Timeline). Every when a date: an inline SVG on a time
  axis (chart/timeline.ts) with one row per lane, spans as bars, instants as dots, a now rule, and
  the chart's zoom along x. Otherwise the ordinal drawing: horizontal up to 6 items, vertical beyond.
  Every word is a text node or a mark's <title>; hi is said as a word (gate: tree.test.ts).
-->
<script lang="ts">
	import type { Component } from './wire';
	import { layoutTimeline, timed } from './chart/timeline';
	import { dimmed, toggle } from './chart/select';
	import { IDENTITY, drag, key, wheel, type Zoom } from './chart/zoom';

	let {
		timeline,
		now = Date.now()
	}: { timeline: Extract<Component, { kind: 'timeline' }>['props']; now?: number } = $props();

	const SCALE = 1.4; // as Chart.svelte: one viewBox unit is 1.4 px past the 320-unit floor
	const clip = $props.id();
	let width = $state(0);
	let zoom: Zoom = $state(IDENTITY);
	let sel: string[] = $state([]);
	let focused = $state('');
	let svg: SVGSVGElement | undefined = $state();

	const isTimed = $derived(timed(timeline.items));
	const g = $derived(
		layoutTimeline(timeline.items, Math.max(320, Math.round(width / SCALE)), zoom, now)
	);
	const live = $derived(
		focused ||
			g.marks
				.filter((m) => sel.includes(m.id))
				.map((m) => m.tip)
				.join('; ')
	);
	const label = $derived(
		`${timeline.title ? `${timeline.title} — ` : ''}timeline, ${timeline.items.length} items on a time axis`
	);

	const plotX = (e: MouseEvent) => {
		const r = svg!.getBoundingClientRect();
		return (e.clientX - r.left) * (g.W / (r.width || g.W)) - g.L;
	};

	$effect(() => {
		const el = svg;
		if (!el) return;
		const on = (e: WheelEvent) => {
			e.preventDefault();
			zoom = wheel(zoom, [plotX(e), 0], e.deltaY, g.box);
		};
		el.addEventListener('wheel', on, { passive: false });
		return () => el.removeEventListener('wheel', on);
	});

	// Capture only once the pointer has moved, so a mark's click is not stolen (face-wm-event-gotchas).
	let press: { id: number; x: number; moved: boolean } | null = null;
	function down(e: PointerEvent) {
		if (e.button === 0) press = { id: e.pointerId, x: plotX(e), moved: false };
	}
	function move(e: PointerEvent) {
		if (!press || press.id !== e.pointerId) return;
		const x = plotX(e);
		if (!press.moved && Math.abs(x - press.x) < 3) return;
		if (!press.moved) svg?.setPointerCapture(e.pointerId);
		zoom = drag(zoom, x - press.x, 0, g.box);
		press = { ...press, x, moved: true };
	}
	function up(e: PointerEvent) {
		if (press?.moved && svg?.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
		press = null;
	}
	function keys(e: KeyboardEvent) {
		const z = key(zoom, e.key, g.box);
		if (z) {
			zoom = z;
			e.preventDefault();
		}
	}
	function markKey(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			sel = toggle(sel, id);
		}
	}
</script>

{#if isTimed}
	<div class="time" data-layout="time" bind:clientWidth={width}>
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
			<defs
				><clipPath id={clip}><rect x={g.L} y="0" width={g.W - g.L - g.R} height={g.H} /></clipPath
				></defs
			>
			<line class="axis" x1={g.L} y1={g.H - g.B} x2={g.W - g.R} y2={g.H - g.B} />
			{#each g.lanes as l}<text class="lane" x={l.x} y={l.y} text-anchor="end" font-size={g.FONT}
					>{l.t}</text
				>{/each}
			{#each g.xLabels as l}<text x={l.x} y={g.H - 5} text-anchor="middle" font-size={g.FONT}
					>{l.t}</text
				>{/each}
			<g clip-path="url(#{clip})">
				{#if g.now !== null}<line class="now" x1={g.now} y1={g.T} x2={g.now} y2={g.H - g.B}
						><title>now</title></line
					>{/if}
				{#each g.marks as m (m.id)}
					{#if m.w !== undefined}
						<rect
							class="span mark"
							class:hi={m.hi}
							class:dim={dimmed(sel, m.id)}
							x={m.x}
							y={m.y - (g.ROW - 6) / 2}
							width={m.w}
							height={g.ROW - 6}
							rx="2"
							tabindex="0"
							role="button"
							aria-pressed={sel.includes(m.id)}
							onclick={() => (sel = toggle(sel, m.id))}
							onkeydown={(e) => markKey(e, m.id)}
							onfocus={() => (focused = m.tip)}
							onblur={() => (focused = '')}><title>{m.tip}</title></rect
						>
					{:else}
						<circle
							class="instant mark"
							class:hi={m.hi}
							class:dim={dimmed(sel, m.id)}
							cx={m.x}
							cy={m.y}
							r="3"
							tabindex="0"
							role="button"
							aria-pressed={sel.includes(m.id)}
							onclick={() => (sel = toggle(sel, m.id))}
							onkeydown={(e) => markKey(e, m.id)}
							onfocus={() => (focused = m.tip)}
							onblur={() => (focused = '')}><title>{m.tip}</title></circle
						>
					{/if}
					{#if m.label}<text x={m.label.x} y={m.label.y} font-size={g.FONT}>{m.label.t}</text>{/if}
				{/each}
			</g>
		</svg>
		<p class="live" aria-live="polite">{live}</p>
		<button type="button" onclick={() => (zoom = IDENTITY)} disabled={zoom.k === 1 && zoom.tx === 0}
			>Reset zoom</button
		>
	</div>
{:else}
	<ol class="timeline" data-layout={timeline.items.length <= 6 ? 'horizontal' : 'vertical'}>
		{#each timeline.items as it}
			<li>
				<span class="when"
					>{it.when}{#if it.until}
						→ {it.until}{/if}</span
				>
				<span>{it.title}</span>
				{#if it.note}<span class="muted"> — {it.note}</span>{/if}
				{#if it.hi}<span class="hi">hi</span>{/if}
				{#if it.lane}<span class="muted">[{it.lane}]</span>{/if}
			</li>
		{/each}
	</ol>
{/if}

<style>
	svg {
		width: 100%;
		display: block;
		touch-action: pan-y;
	}
	text {
		fill: var(--muted);
		font-family: ui-sans-serif, system-ui, sans-serif;
	}
	.lane {
		fill: var(--fg);
	}
	.axis {
		stroke: var(--glass-brd);
	}
	.now {
		stroke: var(--bad-ink);
		stroke-dasharray: 2 2;
	}
	.mark {
		fill: var(--accent);
		cursor: pointer;
		transition: opacity 120ms;
	}
	.mark.hi {
		fill: var(--warn);
	}
	.mark:focus-visible {
		outline: none;
		stroke: var(--fg);
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
	button {
		font-size: 11px;
	}
	.timeline {
		display: flex;
		gap: 10px;
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.timeline[data-layout='vertical'] {
		flex-direction: column;
	}
	.timeline li {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.when,
	.hi {
		font-family: ui-monospace, monospace;
	}
	.hi {
		font-weight: 700;
	}
	.muted {
		color: var(--muted);
	}
	@media (prefers-reduced-motion: reduce) {
		.mark {
			transition: none;
		}
	}
</style>
