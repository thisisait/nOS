<!--
  One workspace: its widgets on a 12-column grid of 40 px rows (workspace-layout.yml).
  The units a drag snaps to are measured from this grid, so a window resize keeps the layout.
  A tab with a lens has a bar over it: one native input per condition; a change re-runs the tab.
-->
<script lang="ts">
	import Widget from './Widget.svelte';
	import type { Widgets } from './widgets';
	import { COLS, ROW_PX, type Grid, type Space } from './workspace';

	type Submit = { form: string; widget: string; values: Record<string, string | number | boolean> };
	let { space, widgets, now, top, onplace, ontop, onrerun, onremove, onsubmit, onlens, onexport }: {
		space: Space; widgets: Widgets; now: number; top: string;
		onplace: (id: string, g: Grid) => void; ontop: (id: string) => void; onrerun: (id: string) => void;
		onremove: (id: string) => void; onsubmit: (m: Submit) => void; onlens: (i: number, value: string) => void;
		onexport?: (name: string, csv: string) => Promise<string>;
	} = $props();
	const OP = { eq: '=', neq: '≠', lt: 'before', gt: 'after', contains: 'contains' } as const;
	const set = (i: number) => (e: Event) => onlens(i, (e.currentTarget as HTMLInputElement | HTMLSelectElement).value);

	const GAP = 8;
	let grid: HTMLElement | undefined = $state();
	const PAD = 32; // .grid padding left + right
	const unit = () => ({ col: ((grid?.clientWidth ?? 1200) - PAD + GAP) / COLS, row: ROW_PX + GAP });
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
<div class="grid" bind:this={grid} style="--gap: {GAP}px; --row: {ROW_PX}px" role="tabpanel" id="panel-{space.id}" aria-labelledby="tab-{space.id}">
	{#each space.widgets as box (box.id)}
		<Widget
			{box}
			state={widgets[box.id]}
			lens={space.lens}
			{now}
			top={top === box.id}
			{unit}
			onplace={(g) => onplace(box.id, g)}
			ontop={() => ontop(box.id)}
			onrerun={() => onrerun(box.id)}
			onremove={() => onremove(box.id)}
			{onsubmit}
			{onexport}
		/>
	{:else}
		<p class="muted">No widgets yet: "+ widget" adds one.</p>
	{/each}
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
