<!--
  A graph the model shows (renderers.rs Graph) as inline SVG: graph/layout.ts places the nodes
  with the face's layered layout. Every node is a focusable <g> with a <rect>, its label as a
  <text> and its whole say (label · id — note [tone]) as a <title>; every edge is a <path> with
  a <title>. Click or Enter selects a node and lights its neighbours; wheel, drag and + - 0 zoom.
-->
<script lang="ts">
	import { layoutGraph, lit, NODE_H, NODE_W, type GraphProps } from './graph/layout';
	import { toggle } from './chart/select';
	import { IDENTITY, drag, key, wheel, type Zoom } from './chart/zoom';

	let { graph }: { graph: GraphProps } = $props();

	const arrow = $props.id();
	let zoom: Zoom = $state(IDENTITY);
	let sel: string[] = $state([]);
	let focused = $state('');
	let svg: SVGSVGElement | undefined = $state();

	const g = $derived(layoutGraph(graph));
	const box = $derived({ w: g.W, h: g.H });
	const on = $derived(lit(sel, graph.edges));
	const live = $derived(
		focused ||
			g.nodes
				.filter((n) => sel.includes(n.id))
				.map(
					(n) =>
						`${n.tip}; linked: ${
							g.nodes
								.filter((m) => m.id !== n.id && on.has(m.id))
								.map((m) => m.text)
								.join(', ') || 'none'
						}`
				)
				.join('; ')
	);
	const label = $derived(
		`${graph.title ? `${graph.title} — ` : ''}graph, ${graph.nodes.length} nodes and ${graph.edges.length} edges`
	);
	const dim = (id: string) => sel.length > 0 && !on.has(id);

	const point = (e: MouseEvent): [number, number] => {
		const r = svg!.getBoundingClientRect();
		const k = g.W / (r.width || g.W);
		return [(e.clientX - r.left) * k, (e.clientY - r.top) * k];
	};

	$effect(() => {
		const el = svg;
		if (!el) return;
		const onWheel = (e: WheelEvent) => {
			e.preventDefault();
			zoom = wheel(zoom, point(e), e.deltaY, box);
		};
		el.addEventListener('wheel', onWheel, { passive: false });
		return () => el.removeEventListener('wheel', onWheel);
	});

	// Capture only once the pointer has moved, so a node's click is not stolen (face-wm-event-gotchas).
	let press: { id: number; at: [number, number]; moved: boolean } | null = null;
	function down(e: PointerEvent) {
		if (e.button === 0) press = { id: e.pointerId, at: point(e), moved: false };
	}
	function move(e: PointerEvent) {
		if (!press || press.id !== e.pointerId) return;
		const p = point(e);
		const [dx, dy] = [p[0] - press.at[0], p[1] - press.at[1]];
		if (!press.moved && Math.hypot(dx, dy) < 3) return;
		if (!press.moved) svg?.setPointerCapture(e.pointerId);
		zoom = drag(zoom, dx, dy, box);
		press = { ...press, at: p, moved: true };
	}
	function up(e: PointerEvent) {
		if (press?.moved && svg?.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
		press = null;
	}
	function keys(e: KeyboardEvent) {
		const z = key(zoom, e.key, box);
		if (z) {
			zoom = z;
			e.preventDefault();
		}
	}
	function nodeKey(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			sel = toggle(sel, id);
		}
	}
</script>

<div class="graph">
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<svg
		bind:this={svg}
		viewBox="0 0 {g.W} {g.H}"
		style:max-width="{g.W * 1.4}px"
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
		<defs>
			<marker
				id={arrow}
				viewBox="0 0 8 8"
				refX="8"
				refY="4"
				markerWidth="6"
				markerHeight="6"
				orient="auto-start-reverse"
			>
				<polygon class="head" points="0 0, 8 4, 0 8" />
			</marker>
		</defs>
		<g transform="translate({zoom.tx} {zoom.ty}) scale({zoom.k})">
			{#each g.edges as e (e.i)}
				<path
					class="edge"
					class:dashed={e.dashed}
					class:dim={dim(e.from) || dim(e.to)}
					d={e.d}
					marker-end="url(#{arrow})"><title>{e.tip}</title></path
				>
				{#if e.label}<text
						class="edge-label"
						x={e.label.x}
						y={e.label.y}
						text-anchor="middle"
						font-size={g.FONT}>{e.label.t}</text
					>{/if}
			{/each}
			{#each g.nodes as n (n.id)}
				<g
					class="node tone-{n.tone ?? 'none'}"
					class:sel={sel.includes(n.id)}
					class:dim={dim(n.id)}
					tabindex="0"
					role="button"
					aria-pressed={sel.includes(n.id)}
					onclick={() => (sel = toggle(sel, n.id))}
					onkeydown={(e) => nodeKey(e, n.id)}
					onfocus={() => (focused = n.tip)}
					onblur={() => (focused = '')}
				>
					<title>{n.tip}</title>
					<rect x={n.x} y={n.y} width={NODE_W} height={NODE_H} rx="5" />
					<text class="label" x={n.x + 4} y={n.y + NODE_H / 2 + g.FONT / 3} font-size={g.FONT}
						>{n.text}</text
					>
				</g>
			{/each}
		</g>
	</svg>
	<p class="live" aria-live="polite">{live}</p>
	<button
		type="button"
		onclick={() => (zoom = IDENTITY)}
		disabled={zoom.k === 1 && zoom.tx === 0 && zoom.ty === 0}>Reset zoom</button
	>
</div>

<style>
	svg {
		width: 100%;
		display: block;
		touch-action: none;
	}
	text {
		font-family: ui-sans-serif, system-ui, sans-serif;
	}
	.label {
		fill: var(--fg);
		pointer-events: none;
	}
	.edge-label {
		fill: var(--muted);
	}
	.edge {
		fill: none;
		stroke: var(--muted);
		stroke-width: 1;
		transition: opacity 120ms;
	}
	.edge.dashed {
		stroke-dasharray: 4 3;
	}
	.head {
		fill: var(--muted);
	}
	.node {
		cursor: pointer;
		transition: opacity 120ms;
	}
	.node rect {
		fill: var(--glass);
		stroke: var(--glass-brd);
	}
	.tone-ok rect {
		stroke: var(--ok-ink);
	}
	.tone-info rect {
		stroke: var(--info-ink);
	}
	.tone-warn rect {
		stroke: var(--warn);
	}
	.tone-bad rect {
		stroke: var(--bad-ink);
	}
	.node.sel rect {
		stroke: var(--accent);
		stroke-width: 2;
	}
	.node:focus-visible {
		outline: none;
	}
	.node:focus-visible rect {
		stroke: var(--fg);
		stroke-width: 2;
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
	@media (prefers-reduced-motion: reduce) {
		.edge,
		.node {
			transition: none;
		}
	}
</style>
