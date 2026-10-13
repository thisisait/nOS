<!--
  One workspace: its widgets on a 12-column grid of 40 px rows (workspace-layout.yml).
  The units a drag snaps to are measured from this grid, so a window resize keeps the layout.
-->
<script lang="ts">
	import Widget from './Widget.svelte';
	import type { Widgets } from './widgets';
	import { COLS, ROW_PX, type Grid, type Space } from './workspace';

	type Submit = { form: string; widget: string; values: Record<string, string | number | boolean> };
	let { space, widgets, now, top, onplace, ontop, onrerun, onremove, onsubmit }: {
		space: Space; widgets: Widgets; now: number; top: string;
		onplace: (id: string, g: Grid) => void; ontop: (id: string) => void; onrerun: (id: string) => void;
		onremove: (id: string) => void; onsubmit: (m: Submit) => void;
	} = $props();

	const GAP = 8;
	let grid: HTMLElement | undefined = $state();
	const PAD = 32; // .grid padding left + right
	const unit = () => ({ col: ((grid?.clientWidth ?? 1200) - PAD + GAP) / COLS, row: ROW_PX + GAP });
</script>

<div class="grid" bind:this={grid} style="--gap: {GAP}px; --row: {ROW_PX}px" role="tabpanel" id="panel-{space.id}" aria-labelledby="tab-{space.id}">
	{#each space.widgets as box (box.id)}
		<Widget
			{box}
			state={widgets[box.id]}
			{now}
			top={top === box.id}
			{unit}
			onplace={(g) => onplace(box.id, g)}
			ontop={() => ontop(box.id)}
			onrerun={() => onrerun(box.id)}
			onremove={() => onremove(box.id)}
			{onsubmit}
		/>
	{:else}
		<p class="muted">No widgets yet: "+ widget" adds one.</p>
	{/each}
</div>

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(12, 1fr);
		grid-auto-rows: var(--row);
		gap: var(--gap);
		padding: 8px 16px 16px;
	}
	.muted {
		grid-column: 1 / span 12;
		color: var(--muted);
	}
</style>
