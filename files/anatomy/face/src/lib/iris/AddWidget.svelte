<!--
  "+ widget": the person names a table and what to show of it. The spec is what the widget
  re-runs as them, without the model (wire.rs WidgetSpec); serve checks every column.
-->
<script lang="ts">
	import type { Value, WidgetSpec } from './wire';

	let {
		onadd,
		oncancel
	}: { onadd: (title: string, spec: WidgetSpec) => void; oncancel: () => void } = $props();

	let table = $state('');
	let title = $state('');
	let q = $state('');
	let where = $state('');
	let kind = $state<'rows' | 'chart' | 'form'>('rows');
	let chart: 'bar' | 'line' | 'pie' = $state('bar');
	let x = $state('');
	let y = $state('');
	let op: 'count' | 'sum' | 'avg' = $state('count');
	let error = $state('');

	function spec(): WidgetSpec {
		const t = table.trim();
		const w = where.trim() ? (JSON.parse(where) as Value[]) : undefined;
		if (w !== undefined && !Array.isArray(w))
			throw new Error('where is a JSON list of {column, op, value}');
		const query = { table: t, ...(q.trim() ? { q: q.trim() } : {}), ...(w ? { where: w } : {}) };
		if (kind === 'form') return { form: { table: t } };
		if (kind === 'rows') return { rows: query };
		return { chart: { query, chart, x: x.trim(), ...(y.trim() ? { y: y.trim() } : {}), op } };
	}

	const ready = $derived(
		!!table.trim() && (kind !== 'chart' || (!!x.trim() && (op === 'count' || !!y.trim())))
	);

	function add(e: SubmitEvent) {
		e.preventDefault();
		try {
			onadd(title.trim() || `${kind} · ${table.trim()}`, spec());
		} catch (err) {
			error = String(err);
		}
	}
</script>

<form class="add" onsubmit={add} aria-label="add a widget">
	<label>table id<input bind:value={table} required placeholder="the KEAP table" /></label>
	<label>title<input bind:value={title} maxlength="120" placeholder="optional" /></label>
	<label>
		show
		<select bind:value={kind}>
			<option value="rows">rows</option>
			<option value="chart">chart</option>
			<option value="form">form (adds a row)</option>
		</select>
	</label>
	{#if kind !== 'form'}
		<label>search<input bind:value={q} placeholder="optional" /></label>
		<label
			>where<input
				bind:value={where}
				placeholder={'optional: [{"column": "kind", "op": "eq", "value": "food"}]'}
			/></label
		>
	{/if}
	{#if kind === 'chart'}
		<label>
			chart
			<select bind:value={chart}
				><option>bar</option><option>line</option><option>pie</option></select
			>
		</label>
		<label>x column<input bind:value={x} required /></label>
		<label>
			op
			<select bind:value={op}><option>count</option><option>sum</option><option>avg</option></select
			>
		</label>
		{#if op !== 'count'}<label>y column (a number)<input bind:value={y} required /></label>{/if}
	{/if}
	{#if error}<p class="error">{error}</p>{/if}
	<div class="row">
		<button type="submit" disabled={!ready}>add</button>
		<button type="button" class="ghost" onclick={oncancel}>cancel</button>
	</div>
</form>

<style>
	.add {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: 8px;
		margin: 0 16px 8px;
		padding: 12px;
		border: 1px solid var(--glass-brd);
		border-radius: 12px;
		background: var(--glass);
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 12px;
		color: var(--muted);
	}
	input,
	select {
		font: inherit;
		color: var(--fg);
		background: var(--bg);
		border: 1px solid var(--glass-brd);
		border-radius: 8px;
		padding: 4px 8px;
	}
	.row {
		display: flex;
		gap: 8px;
		align-items: end;
	}
	.error {
		grid-column: 1 / -1;
		margin: 0;
		color: var(--bad);
	}
	button {
		border: 1px solid var(--glass-brd);
		background: var(--accent);
		color: var(--bg);
		border-radius: 10px;
		padding: 4px 12px;
	}
	button.ghost {
		background: none;
		color: var(--muted);
	}
	button:disabled {
		opacity: 0.4;
	}
</style>
