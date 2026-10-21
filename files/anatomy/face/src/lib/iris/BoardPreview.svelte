<!--
  A child board drawn on its card (CanvasItem.svelte): its items at their world places, centred and
  scaled to fit w x h by one CSS transform. Inert and pointer-less: the card's double-click and Enter
  still open it. It runs nothing: a widget shows the answer already held, or says "open to load".
-->
<script lang="ts">
	import ComponentView from './Component.svelte';
	import type { Widgets } from './widgets';
	import type { Item, Space } from './workspace';

	let {
		items,
		widgets,
		spaces,
		w,
		h
	}: { items: Item[]; widgets: Widgets; spaces: Space[]; w: number; h: number } = $props();

	const fit = $derived.by(() => {
		const x0 = Math.min(...items.map((i) => i.x)),
			y0 = Math.min(...items.map((i) => i.y));
		const bw = Math.max(...items.map((i) => i.x + i.w)) - x0,
			bh = Math.max(...items.map((i) => i.y + i.h)) - y0;
		const k = Math.min(w / bw, h / bh, 1);
		return { x0, y0, bw, bh, k, tx: (w - bw * k) / 2, ty: (h - bh * k) / 2 };
	});
	const nameOf = (id: string) => spaces.find((s) => s.id === id)?.name ?? id;
</script>

<div class="view" style:width="{w}px" style:height="{h}px">
	{#if items.length}
		<div
			class="world"
			data-preview
			inert
			style:width="{fit.bw}px"
			style:height="{fit.bh}px"
			style:transform="translate({fit.tx}px, {fit.ty}px) scale({fit.k})"
		>
			{#each items as i (i.id)}
				<div
					class="item {i.kind}"
					style:left="{i.x - fit.x0}px"
					style:top="{i.y - fit.y0}px"
					style:width="{i.w}px"
					style:height="{i.h}px"
				>
					{#if i.kind === 'widget'}
						{@const c = widgets[i.id]?.component}
						<h2>{i.title}</h2>
						<div class="body">
							{#if c}<ComponentView component={c} />{:else}<p class="muted">open to load</p>{/if}
						</div>
					{:else if i.kind === 'heading'}
						<strong>{i.text}</strong>
					{:else if i.kind === 'frame'}
						<span class="muted">{i.title}</span>
					{:else}
						<span>{nameOf(i.board)}</span>
					{/if}
				</div>
			{/each}
		</div>
	{:else}
		<p class="muted">empty board</p>
	{/if}
</div>

<style>
	.view {
		position: relative;
		overflow: hidden;
		margin: 0 8px;
	}
	.world {
		position: absolute;
		transform-origin: 0 0;
		pointer-events: none;
	}
	.item {
		position: absolute;
		box-sizing: border-box;
		overflow: hidden;
		border-radius: 12px;
	}
	.widget,
	.board {
		border: 1px solid var(--glass-brd);
		background: var(--glass);
	}
	.frame {
		border: 2px dashed var(--glass-brd);
		padding: 4px 6px;
	}
	.heading strong {
		font-size: 24px;
	}
	.board span {
		display: block;
		padding: 4px 6px;
	}
	h2 {
		margin: 0;
		padding: 6px 8px;
		font-size: 13px;
		border-bottom: 1px solid var(--glass-brd);
	}
	.body {
		padding: 8px;
	}
	.muted {
		margin: 0;
		color: var(--muted);
		font-size: 11px;
	}
</style>
