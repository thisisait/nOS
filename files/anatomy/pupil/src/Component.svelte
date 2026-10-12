<!--
  One component of the closed vocabulary (nos_contract::renderers::Component),
  drawn as the terminal shell words it (shell.rs component_lines). Every value
  is a text node; an unknown or unreadable source is listed, never shown as empty.
-->
<script lang="ts">
	import Badge from '$ui/Badge.svelte';
	import StatusNote from '$ui/StatusNote.svelte';
	import { severityTone } from '$ui/tone';
	import { cell, shown, type Component } from './wire';

	let { component }: { component: Component } = $props();
</script>

<section class="component" data-kind={component.kind}>
	{#if component.kind === 'table_results'}
		{@const t = component.props}
		<h3>
			{t.table} — {t.rows.length} row(s)
			{#if t.projected}<Badge tone="info">semantic</Badge>{:else}<Badge tone="warn">substring match, not semantic</Badge>{/if}
		</h3>
		<table>
			<thead><tr><th>__id</th>{#each t.columns as c}<th>{c}</th>{/each}</tr></thead>
			<tbody>
				{#each t.rows as r}
					<tr><td class="mono">{r.__id}</td>{#each t.columns as c}<td>{cell(r.cells[c])}</td>{/each}</tr>
				{/each}
			</tbody>
		</table>
	{:else if component.kind === 'row_diff_approval'}
		{@const d = component.props}
		<h3>edit {d.table} / {d.row_id} — nothing is written unless you approve</h3>
		<ul class="diff">
			{#each d.cells as ch}
				<li><b>{ch.key}</b>: <span class="old">{shown(ch.old)}</span> → <span class="new">{shown(ch.new)}</span></li>
			{/each}
		</ul>
	{:else if component.kind === 'inbox_list'}
		{@const i = component.props}
		<h3>inbox — {i.items.length} waiting</h3>
		<ul>
			{#each i.items as x}
				<li><Badge>{x.source}</Badge> {x.title} <span class="muted">{x.created_at} ({x.id})</span></li>
			{/each}
		</ul>
		{#each i.refused as r}<StatusNote kind="unwired" block={false}>{r}</StatusNote>{/each}
	{:else if component.kind === 'approvals_list'}
		{@const a = component.props}
		<h3>{a.items.length} awaiting you</h3>
		<ul>
			{#each a.items as x}
				<li>
					<Badge tone={severityTone(x.severity)}>{x.severity.toUpperCase()}</Badge>
					<span class="muted">{x.kind} · {x.age}</span> {x.what}
					<div class="muted">{x.where}{#if x.note} · {x.note}{/if}</div>
				</li>
			{/each}
		</ul>
		{#each a.unknown as u}
			<StatusNote kind="unwired" block={false}>source unreadable, so its state is UNKNOWN not empty: {u}</StatusNote>
		{/each}
	{:else if component.kind === 'red_status'}
		{@const r = component.props}
		<h3>{r.red_count === 0 ? 'nothing red' : `${r.red_count} red`}</h3>
		<ul>{#each r.reds as x}<li class="bad">✗ {x}</li>{/each}</ul>
		{#if r.hold_count > 0}
			<p>{r.hold_count} on hold (intentional)</p>
			<ul>{#each r.holds as x}<li>⏸ {x}</li>{/each}</ul>
		{/if}
	{:else}
		<!-- Unreachable past the bridge's decoder; said aloud if it ever is. -->
		<StatusNote kind="error" title="refused">no renderer for component kind {(component as { kind: string }).kind}</StatusNote>
	{/if}
</section>

<style>
	.component {
		padding: 10px 12px;
		border: 1px solid var(--glass-brd);
		border-radius: 10px;
		background: var(--glass);
	}
	h3 {
		margin: 0 0 6px;
		font-size: 13px;
		display: flex;
		gap: 8px;
		align-items: center;
	}
	table {
		border-collapse: collapse;
		font-size: 12px;
		width: 100%;
	}
	th,
	td {
		text-align: left;
		padding: 3px 8px;
		border-bottom: 1px solid var(--glass-brd);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	ul {
		margin: 0;
		padding-left: 16px;
		font-size: 12px;
	}
	.mono,
	.diff {
		font-family: ui-monospace, monospace;
	}
	/* shell.rs wrap: no part of a value off screen, or the end marker lies about it. */
	.diff li {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.muted {
		color: var(--muted);
	}
	.bad,
	.old {
		color: var(--bad-ink);
	}
	.new {
		color: var(--ok-ink);
	}
</style>
