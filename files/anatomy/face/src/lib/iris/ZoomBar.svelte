<!-- The canvas zoom: −, the zoom as a percentage (a click is 100%), +, and fit to the items. -->
<script lang="ts">
	import { Panel, useSvelteFlow, useViewport } from '@xyflow/svelte';

	const flow = useSvelteFlow();
	const view = useViewport();
</script>

<Panel position="bottom-left">
	<div class="zoom" role="group" aria-label="zoom">
		<button aria-label="zoom out" onclick={() => flow.zoomOut()}>−</button>
		<button aria-label="zoom to 100%" onclick={() => flow.setZoom(1)}
			>{Math.round(view.current.zoom * 100)}%</button
		>
		<button aria-label="zoom in" onclick={() => flow.zoomIn()}>+</button>
		<button aria-label="fit to the items" onclick={() => flow.fitView({ padding: 0.1 })}>fit</button
		>
	</div>
</Panel>

<style>
	.zoom {
		display: flex;
		border: 1px solid var(--glass-brd);
		border-radius: 8px;
		background: var(--glass);
	}
	button {
		min-width: 32px;
		border: 0;
		background: none;
		color: var(--fg);
		cursor: pointer;
		font-variant-numeric: tabular-nums;
	}
	button:focus-visible {
		outline: 2px solid var(--accent);
	}
</style>
