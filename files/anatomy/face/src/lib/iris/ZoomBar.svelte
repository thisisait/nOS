<!-- The canvas zoom: −, the zoom as a percentage (a click is 100%), +, and fit to the items; the keys - 0 + f too (Workspace.svelte). -->
<script lang="ts">
	import { Panel, useSvelteFlow, useViewport } from '@xyflow/svelte';

	const flow = useSvelteFlow();
	const view = useViewport();
	const KEYS: Record<string, () => unknown> = {
		'+': () => flow.zoomIn(),
		'=': () => flow.zoomIn(),
		'-': () => flow.zoomOut(),
		'0': () => flow.setZoom(1),
		f: () => flow.fitView({ padding: 0.1 })
	};
	/** + / - / 0 / f zoom in, out, to 100% and to fit; false for any other key. */
	export function zoomKey(key: string): boolean {
		const f = KEYS[key];
		if (f) f();
		return !!f;
	}
	/** A client point (the canvas's centre) in world px. */
	export const toWorld = (x: number, y: number) => flow.screenToFlowPosition({ x, y });
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
