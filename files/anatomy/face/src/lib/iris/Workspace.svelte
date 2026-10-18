<!--
  One board: an infinite canvas (Svelte Flow, MIT) of widgets, headings, frames and boards in world px
  (workspace-layout.yml v3); a board card opens its child by double-click or Enter. Wheel or pinch zooms, dragging the background pans, −/100%/+/fit sit
  bottom left (keys - 0 + f); Tab walks the items top-left first; a focused item moves by arrows and resizes by shift+arrows. Svelte Flow's own CSS
  carries colour literals, so it is not imported: the few structural rules it needs are below.
  A board with a lens has a bar over it: one native input per condition; a change re-runs the board.
-->
<script module lang="ts">
	import type { Widgets } from './widgets';
	import type { Box, Space } from './workspace';
	import type { Lens } from './wire';

	type Submit = { form: string; widget: string; values: Record<string, string | number | boolean> };
	/** What every CanvasItem reads; getters, so a new answer redraws without a new node. */
	export type CanvasCtx = {
		readonly widgets: Widgets;
		readonly lens: Lens[] | undefined;
		readonly now: number;
		readonly top: string;
		readonly spaces: Space[];
		onopen: (id: string) => void;
		onplace: (id: string, g: Box) => void;
		ontop: (id: string) => void;
		ontext: (id: string, text: string) => void;
		onrerun: (id: string) => void;
		onremove: (id: string) => void;
		onsubmit: (m: Submit) => void;
		onexport?: (name: string, csv: string) => Promise<string>;
	};
</script>

<script lang="ts">
	import { SvelteFlow, type Node, type Viewport } from '@xyflow/svelte';
	import { setContext, untrack } from 'svelte';
	import CanvasItem from './CanvasItem.svelte';
	import ZoomBar from './ZoomBar.svelte';
	import { byKey, SNAP, type Item, type View } from './workspace';

	let {
		space,
		spaces,
		onopen,
		widgets,
		now,
		top,
		onplace,
		ontop,
		ontext,
		onview,
		onrerun,
		onremove,
		onsubmit,
		onlens,
		onexport
	}: Omit<CanvasCtx, 'lens'> & {
		space: Space;
		onview: (v: View) => void;
		onlens: (i: number, value: string) => void;
	} = $props();
	const OP = { eq: '=', neq: '≠', lt: 'before', gt: 'after', contains: 'contains' } as const;
	const set = (i: number) => (e: Event) =>
		onlens(i, (e.currentTarget as HTMLInputElement | HTMLSelectElement).value);

	setContext<CanvasCtx>('iris-canvas', {
		get widgets() {
			return widgets;
		},
		get lens() {
			return space.lens;
		},
		get now() {
			return now;
		},
		get top() {
			return top;
		},
		get spaces() {
			return spaces;
		},
		onopen: (id) => onopen(id),
		onplace: (id, g) => onplace(id, g),
		ontop: (id) => ontop(id),
		ontext: (id, t) => ontext(id, t),
		onrerun: (id) => onrerun(id),
		onremove: (id) => onremove(id),
		onsubmit: (m) => onsubmit(m),
		onexport: (n, csv) => (onexport ? onexport(n, csv) : Promise.resolve('not saved'))
	});

	const nodeTypes = { item: CanvasItem };
	const label = (i: Item) =>
		i.kind === 'board'
			? (spaces.find((s) => s.id === i.board)?.name ?? i.board)
			: i.kind === 'heading'
				? i.text
				: i.title;
	// Reading order (top-left first), so Tab walks it; zIndex draws frames behind, the raised widget over the rest.
	const toNodes = (items: Item[], raised: string, was: Node[]): Node[] => {
		const sel = new Set(was.filter((n) => n.selected).map((n) => n.id));
		return [...items]
			.sort((a, b) => a.y - b.y || a.x - b.x)
			.map((i) => ({
				id: i.id,
				type: 'item',
				position: { x: i.x, y: i.y },
				width: i.w,
				height: i.h,
				data: { item: i },
				dragHandle: '.move',
				zIndex: i.kind === 'frame' ? 0 : i.id === raised ? 2 : 1,
				selected: sel.has(i.id),
				ariaLabel: `${i.kind} ${label(i)}`
			}));
	};
	let nodes: Node[] = $state.raw([]);
	$effect.pre(() => {
		const next = toNodes(
			space.items,
			top,
			untrack(() => nodes)
		);
		nodes = next;
	});

	const at = (id: string) => space.items.find((i) => i.id === id);
	const dropped = ({ nodes: moved }: { nodes: Node[] }) => {
		for (const n of moved) {
			const i = at(n.id);
			if (i) onplace(i.id, { ...i, x: n.position.x, y: n.position.y });
		}
	};
	// Capture: before Svelte Flow's own arrow handling, which moves 5 px and never resizes.
	const key = (e: KeyboardEvent) => {
		const t = e.target as HTMLElement;
		if (t.closest('input, textarea, select, [contenteditable]')) return;
		if (!e.ctrlKey && !e.metaKey && !e.altKey && bar?.zoomKey(e.key)) return e.preventDefault();
		const id = t.closest<HTMLElement>('.svelte-flow__node')?.dataset.id;
		const i = id && at(id);
		if (i && i.kind === 'board' && e.key === 'Enter' && !t.closest('button')) {
			e.preventDefault();
			return onopen(i.board);
		}
		const g = i && byKey(i, e.key, e.shiftKey);
		if (!i || !g) return;
		e.preventDefault();
		e.stopPropagation();
		onplace(i.id, g);
	};
	const moveEnd = (_: unknown, v: Viewport) => onview(v);
	let bar: ZoomBar | undefined = $state();
	let canvas: HTMLElement;
	/** The centre of the view in world px: where a new item lands. */
	export function centre() {
		const r = canvas.getBoundingClientRect();
		return bar?.toWorld(r.left + r.width / 2, r.top + r.height / 2);
	}
</script>

{#if space.lens?.length}
	<div class="lens" role="group" aria-label="lens of {space.name}">
		{#each space.lens as c, i}
			<label>
				<span>{c.column} {OP[c.op]}</span>
				{#if c.options?.length}
					<select value={c.value} onchange={set(i)}>
						<option value="">any</option>
						{#each c.options as o}<option value={o}>{o}</option>{/each}
					</select>
				{:else if c.kind === 'date'}
					<input type="date" value={c.value} onchange={set(i)} />
				{:else}
					<input type="text" value={c.value} onchange={set(i)} placeholder="any" />
				{/if}
			</label>
		{/each}
	</div>
{/if}
<div
	class="canvas"
	role="region"
	tabindex="-1"
	bind:this={canvas}
	aria-label="board {space.name}"
	onkeydowncapture={key}
>
	{#if !space.items.length}
		<p class="muted">No widgets yet: "+ widget" adds one.</p>
	{/if}
	{#key space.id}
		<SvelteFlow
			bind:nodes
			{nodeTypes}
			initialViewport={space.view ?? { x: 0, y: 0, zoom: 1 }}
			minZoom={0.1}
			maxZoom={4}
			snapGrid={[SNAP, SNAP]}
			nodesConnectable={false}
			elevateNodesOnSelect={false}
			zoomOnDoubleClick={false}
			deleteKey={null}
			proOptions={{ hideAttribution: true }}
			onnodedragstop={dropped}
			onmoveend={moveEnd}
		>
			<ZoomBar bind:this={bar} />
		</SvelteFlow>
	{/key}
</div>

<style>
	.lens {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 16px;
		padding: 8px 16px 0;
		font-size: 12px;
	}
	.lens label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.lens span {
		color: var(--muted);
	}
	.canvas {
		position: relative;
		flex: 1;
		min-height: 360px;
	}
	.muted {
		position: absolute;
		z-index: 1;
		margin: 16px;
		color: var(--muted);
		pointer-events: none;
	}
	/* Svelte Flow's structural rules (@xyflow/svelte dist/base.css, MIT), with no colour of its own. */
	.canvas :global(.svelte-flow__container) {
		position: absolute;
		inset: 0;
	}
	.canvas :global(.svelte-flow__pane) {
		z-index: 1;
		touch-action: none;
		cursor: grab;
	}
	.canvas :global(.svelte-flow__viewport),
	.canvas :global(.svelte-flow__nodes) {
		transform-origin: 0 0;
		pointer-events: none;
	}
	.canvas :global(.svelte-flow__viewport) {
		z-index: 2;
	}
	.canvas :global(.svelte-flow__renderer) {
		z-index: 4;
	}
	.canvas :global(.svelte-flow__selection) {
		z-index: 6;
		border: 1px dashed var(--accent);
	}
	.canvas :global(.svelte-flow__node) {
		position: absolute;
		box-sizing: border-box;
		pointer-events: all;
		transform-origin: 0 0;
		border-radius: 12px;
	}
	.canvas :global(.svelte-flow__node:focus-visible),
	.canvas :global(.svelte-flow__node.selected) {
		outline: 2px solid var(--accent);
	}
	.canvas :global(.svelte-flow__panel) {
		position: absolute;
		z-index: 5;
		margin: 12px;
	}
	.canvas :global(.svelte-flow__panel.bottom) {
		bottom: 0;
	}
	.canvas :global(.svelte-flow__panel.left) {
		left: 0;
	}
</style>
