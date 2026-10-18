<!--
  A dashboard Iris offers (renderers.rs Dashboard): its name, lens, widgets and what serve left out,
  every word a text node. Nothing runs here: "Place here" or "Place on a new board" hands the offer to `onplace`
  (workspace.ts placeOffer), once; the model never places or runs it.
-->
<script lang="ts">
	import { tableOf } from './widgets';
	import type { DashboardProps, Lens, WidgetSpec } from './wire';

	let {
		dashboard,
		onplace
	}: { dashboard: DashboardProps; onplace?: (d: DashboardProps, here: boolean) => boolean } =
		$props();

	let placed = $state(false);
	const OP: Record<Lens['op'], string> = {
		eq: '=',
		neq: '≠',
		lt: '<',
		gt: '>',
		contains: 'contains'
	};
	const kind = (s: WidgetSpec) =>
		'rows' in s ? 'rows' : 'chart' in s ? `${s.chart.chart} chart` : 'kpi' in s ? 'kpi' : 'form';
</script>

<section class="dashboard">
	<h3>
		{dashboard.name}
		<span class="muted">— {dashboard.widgets.length} widgets, nothing runs until you place it</span>
	</h3>
	{#if dashboard.lens.length}
		<p class="muted">
			lens: {#each dashboard.lens as l, i}{i ? '; ' : ''}{l.column}
				{OP[l.op]}
				{l.value || '(unset)'}{/each}
		</p>
	{/if}
	<ul>
		{#each dashboard.widgets as w}<li>
				{w.title} <span class="muted">({kind(w.spec)}, table {tableOf(w.spec)})</span>
			</li>{/each}
	</ul>
	{#if dashboard.dropped.length}
		<ul class="dropped">
			{#each dashboard.dropped as d}<li>left out: {d.title} — {d.why}</li>{/each}
		</ul>
	{/if}
	{#if placed}
		<p class="muted">Placed</p>
	{:else}
		<div class="place">
			<button
				type="button"
				disabled={!onplace}
				onclick={() => (placed = onplace?.(dashboard, true) ?? false)}>Place here</button
			>
			<button
				type="button"
				disabled={!onplace}
				onclick={() => (placed = onplace?.(dashboard, false) ?? false)}>Place on a new board</button
			>
		</div>
	{/if}
</section>

<style>
	.dashboard {
		display: grid;
		gap: 6px;
		padding: 10px 12px;
		border: 1px solid var(--glass-brd);
		border-radius: 10px;
		background: var(--glass);
		font-size: 12px;
	}
	h3,
	p,
	ul {
		margin: 0;
	}
	h3 {
		font-size: 13px;
	}
	ul {
		padding-left: 18px;
	}
	.muted {
		color: var(--muted);
		font-weight: normal;
	}
	.dropped {
		color: var(--warn, var(--muted));
	}
	.place {
		display: flex;
		gap: 6px;
	}
</style>
