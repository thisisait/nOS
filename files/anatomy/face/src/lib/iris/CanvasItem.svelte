<!--
  One item on the canvas, as a Svelte Flow node: a live widget, an editable heading, a frame
  (a titled rectangle behind the others), or a board card that opens its child on double-click. Every kind has a `.move` grip (the node's drag handle)
  and a resize corner; pointer capture is on the corner only (face-wm-event-gotchas).
-->
<script lang="ts">
	import { useSvelteFlow, type NodeProps } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import Widget from './Widget.svelte';
	import type { CanvasCtx } from './Workspace.svelte';
	import { byPointer, type Box, type Item } from './workspace';

	let { data }: NodeProps = $props();
	const item = $derived(data.item as Item);
	const c = getContext<CanvasCtx>('iris-canvas');
	const flow = useSvelteFlow();

	let drag: { start: Box; cx: number; cy: number; zoom: number } | null = null;
	const grab = (e: PointerEvent) => {
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		const { x, y, w, h } = item;
		drag = { start: { x, y, w, h }, cx: e.clientX, cy: e.clientY, zoom: flow.getZoom() };
		c.ontop(item.id);
	};
	const moved = (e: PointerEvent) => {
		if (drag)
			c.onplace(
				item.id,
				byPointer(drag.start, 'resize', e.clientX - drag.cx, e.clientY - drag.cy, drag.zoom)
			);
	};
	const up = () => (drag = null);
	const typed = (e: Event) => c.ontext(item.id, (e.currentTarget as HTMLInputElement).value);
</script>

{#if item.kind === 'widget'}
	<Widget
		box={item}
		state={c.widgets[item.id]}
		lens={c.lens}
		now={c.now}
		top={c.top === item.id}
		ontop={() => c.ontop(item.id)}
		onrerun={() => c.onrerun(item.id)}
		onremove={() => c.onremove(item.id)}
		onsubmit={c.onsubmit}
		onexport={c.onexport}
		onread={c.onread}
	/>
{:else if item.kind === 'board'}
	{@const child = c.spaces.find((s) => s.id === item.board)}
	{@const n = child?.items.length ?? 0}
	<!-- A double-click opens it; so does Enter on the focused node (Workspace.svelte). -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<section class="board" ondblclick={() => c.onopen(item.board)}>
		<header>
			<button class="grip move" aria-label="move board (arrows move, shift+arrows resize)">⠿</button
			>
			<strong>{child?.name ?? item.board}</strong>
			<button class="grip" aria-label="remove board" onclick={() => c.onremove(item.id)}>×</button>
		</header>
		<p>{n} {n === 1 ? 'item' : 'items'}</p>
	</section>
{:else}
	<section class={item.kind}>
		<header>
			<button class="grip move" aria-label="move {item.kind} (arrows move, shift+arrows resize)"
				>⠿</button
			>
			<input
				class="nodrag"
				value={item.kind === 'heading' ? item.text : item.title}
				maxlength="120"
				aria-label="{item.kind} text"
				onchange={typed}
			/>
			<button class="grip" aria-label="remove {item.kind}" onclick={() => c.onremove(item.id)}
				>×</button
			>
		</header>
	</section>
{/if}
<button
	class="resize nodrag"
	aria-label="resize (shift+arrows)"
	tabindex="-1"
	onpointerdown={grab}
	onpointermove={moved}
	onpointerup={up}
	onpointercancel={up}
></button>

<style>
	section {
		width: 100%;
		height: 100%;
		box-sizing: border-box;
	}
	.board {
		border: 1px solid var(--glass-brd);
		border-radius: 12px;
		background: var(--glass);
		cursor: zoom-in;
	}
	.board strong {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.board p {
		margin: 0 12px;
		color: var(--muted);
		font-size: 11px;
	}
	.frame {
		border: 2px dashed var(--glass-brd);
		border-radius: 12px;
		background: var(--glass);
	}
	header {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 6px;
	}
	input {
		flex: 1;
		min-width: 0;
		border: 0;
		background: none;
		color: var(--fg);
		font: inherit;
	}
	.heading input {
		font-size: 24px;
		font-weight: 600;
	}
	.frame input {
		color: var(--muted);
		font-size: 13px;
	}
	.grip {
		border: 0;
		background: none;
		color: var(--muted);
		touch-action: none;
	}
	.move {
		cursor: grab;
	}
	.resize {
		position: absolute;
		right: 2px;
		bottom: 2px;
		width: 14px;
		height: 14px;
		padding: 0;
		cursor: nwse-resize;
		background: none;
		border: 0;
		border-right: 2px solid var(--muted);
		border-bottom: 2px solid var(--muted);
		border-radius: 0 0 8px 0;
		touch-action: none;
	}
	.grip:focus-visible,
	input:focus-visible {
		outline: 2px solid var(--accent);
	}
</style>
