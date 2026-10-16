<!--
  One component of the closed vocabulary (nos_contract::renderers::Component),
  drawn as the terminal shell words it (shell.rs component_lines). Every value
  is a text node; an unknown or unreadable source is listed, never shown as empty.
-->
<script lang="ts">
	import Badge from '$ui/Badge.svelte';
	import StatusNote from '$ui/StatusNote.svelte';
	import { severityTone } from '$ui/tone';
	import Chart from './Chart.svelte';
	import Form from './Form.svelte';
	import Graph from './Graph.svelte';
	import Sequence from './Sequence.svelte';
	import Markdown from './Markdown.svelte';
	import Timeline from './Timeline.svelte';
	import { inherit, MARK, shownIn, tally, treeDeltas, VIEWS, type Delta, type View } from './delta';
	import { isMoney, number, shownValue, signed } from './fmt';
	import { cell, shown, type Component, type SchemaColumn, type TreeNode, type Value } from './wire';
	/** A new column as both shells say it (shell.rs column_said): kind, required, options, where a rowRef points. */
	const columnSaid = (c: SchemaColumn) => c.kind + (c.required ? ', required' : '') + (c.options ? ` of ${c.options.join(', ')}` : '')
		+ (c.ref_table ? ` → ${c.ref_title ?? c.ref_table} (${c.ref_table})` : '') + (c.ref_display ? `, shown by ${c.ref_display}` : '');

	// view: Před / Změny / Po of a component that marks a delta (delta.ts); the switch sets it.
	let { component, view = $bindable('changes') }: { component: Component; view?: View } = $props();
	// One name per switch: one group for the keyboard and a screen reader; two switches never merge.
	const switchName = $props.id();
	// A column whose text runs long reads as prose under its row, not as a column that starves the rest.
	const LONG = (s: string) => s.length > 80 || s.includes('\n');
</script>

<!-- The mark is text (+ − ~) and its word for a screen reader; the colour is only on top. -->
{#snippet mark(d: Delta | undefined)}{#if d}<span class="mark" data-delta={d}>{MARK[d]}</span><span class="sr">{d}</span>{' '}{/if}{/snippet}
{#snippet deltaBar(ds: (Delta | undefined)[])}
	{#if ds.some(Boolean)}
		<div class="delta-bar">
			<span class="mono">{tally(ds)}</span>
			<fieldset class="views">
				<legend class="sr">pohled</legend>
				{#each VIEWS as [v, label]}<label><input type="radio" name={switchName} bind:group={view} value={v} />{label}</label>{/each}
			</fieldset>
		</div>
	{/if}
{/snippet}
{#snippet value(v: Value | undefined, key: string)}{#if v !== null && typeof v === 'object'}<pre>{JSON.stringify(v, null, 1)}</pre>{:else}{shownValue(v, key)}{/if}{/snippet}

<section class="component" data-kind={component.kind}>
	{#if component.kind === 'table_results'}
		{@const t = component.props}
		<h3>
			<!-- A count (limit 0) is the count; an empty grid of every column says nothing more. -->
			{t.name} — {#if t.rows.length}{t.rows.length}{' of '}{/if}{t.matched} matched ({t.total} rows)
			{#if t.projected}<Badge tone="info">semantic</Badge>{:else}<Badge tone="warn">substring match, not semantic</Badge>{/if}
		</h3>
		<p class="muted query">{t.query}</p>
		{@const long = t.columns.filter((c) => t.rows.some((r) => LONG(cell(r.cells[c]))))}
		{@const short = t.columns.filter((c) => !long.includes(c))}
		{#if t.rows.length}
		<div class="scroll">
			<table>
				<thead><tr>{#each short as c}<th>{c}</th>{/each}</tr></thead>
				<tbody>
					{#each t.rows as r}
						<tr>{#each short as c}<td>{shownValue(r.cells[c], c)}</td>{/each}</tr>
						<!-- A fold only for long text; an id already on screen (a group's value) needs none. -->
						{#if long.length || !short.some((c) => cell(r.cells[c]) === r.__id)}
						<tr class="more">
							<td colspan={Math.max(short.length, 1)}>
								<details>
									<summary class="muted mono">{r.__id}{#each long as c}{' · '}{c}{/each}</summary>
									{#each long as c}<div class="field"><b>{c}</b><div>{cell(r.cells[c])}</div></div>{/each}
								</details>
							</td>
						</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
		{/if}
	{:else if component.kind === 'row_diff_approval'}
		{@const d = component.props}
		<h3>{d.row_id === undefined ? `${d.op} a new row in ${d.title} (${d.table})` : `${d.op} ${d.title} (${d.table}) / ${d.row_id}`} — nothing is written unless you approve</h3>
		{#if d.warning}<p><strong class="bad">! {d.warning}</strong></p>{/if}
		{#if d.read_from?.length}<p><Badge tone="warn">contains text from {d.read_from.join(', ')}</Badge></p>{/if}
		{#if d.op === 'delete'}<p class="bad">approve deletes the whole row: every value below is gone</p>{/if}
		<ul class="diff">
			{#each d.cells as ch}
				{#if d.op === 'insert_many' && d.row_id !== undefined}
					<li><b>{ch.key}</b>: {shown(ch.new)} <span class="muted">(unchanged)</span></li>
				{:else if d.op === 'delete'}
					<li><b>{ch.key}</b>: <span class="old">{shown(ch.old)}</span> → <span class="bad">(deleted)</span></li>
				{:else}
					<li><b>{ch.key}</b>: <span class="old">{shown(ch.old)}</span> → <span class="new">{shown(ch.new)}</span></li>
				{/if}
			{/each}
		</ul>
		{#if d.lines}
			{@const l = d.lines}
			{#each l.rows as row, i}
				<p class="muted">+ line {i + 1} of {l.rows.length} in {l.title} ({l.table}), its {l.ref_key} → the row above</p>
				<ul class="diff">
					{#each row as ch}
						<li><b>{ch.key}</b>: <span class="old">{shown(ch.old)}</span> → <span class="new">{shown(ch.new)}</span></li>
					{/each}
				</ul>
			{/each}
		{/if}
	{:else if component.kind === 'table_schema_approval'}
		{@const t = component.props}
		<h3>create table {t.title}, {t.visibility} to you — nothing is created unless you approve</h3>
		{#if t.description}<p class="muted">{t.description}</p>{/if}
		<ul class="diff">
			{#each t.columns as c}
				<li><b>{c.key}</b> ({c.label}): {columnSaid(c)}</li>
			{/each}
		</ul>
	{:else if component.kind === 'column_add_approval'}
		{@const t = component.props}
		<h3>add columns to {t.title} ({t.table}) — nothing is added unless you approve</h3>
		<ul class="diff">
			{#each t.existing as c}
				<li class="muted">has <b>{c.key}</b> ({c.label}): {c.kind}</li>
			{/each}
			{#each t.columns as c}
				<li>+ <b>{c.key}</b> ({c.label}): {columnSaid(c)}</li>
			{/each}
		</ul>
		<p class="muted">existing rows get no value in the new columns</p>
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
	{:else if component.kind === 'markdown'}
		<Markdown text={component.props.text} />
	{:else if component.kind === 'table'}
		{@const t = component.props}
		{#if t.title}<h3>{t.title}</h3>{/if}
		<div class="scroll">
			<table>
				<thead><tr>{#each t.columns as c}<th>{c}</th>{/each}</tr></thead>
				<tbody>{#each t.rows as r}<tr>{#each r as v, i}<td>{shownValue(v, t.columns[i] ?? '')}</td>{/each}</tr>{/each}</tbody>
			</table>
		</div>
	{:else if component.kind === 'list'}
		{@const l = component.props}
		{#if l.title}<h3>{l.title}</h3>{/if}
		{@render deltaBar(l.items.map((x) => x.delta))}
		<!-- Each item keeps its number in the whole list (shell.rs), so Před and Po do not renumber. -->
		{@const items = l.items.map((x, i) => ({ ...x, n: i + 1 })).filter((x) => shownIn(x.delta, view))}
		{#snippet item(x: (typeof items)[number])}
			<li data-delta={x.delta} value={l.ordered ? x.n : undefined}>{@render mark(x.delta)}{#if x.tone}<Badge tone={x.tone}>{x.tone}</Badge>{' '}{/if}{x.text}{#if x.detail}<span class="muted"> — {x.detail}</span>{/if}</li>
		{/snippet}
		{#if l.ordered}<ol>{#each items as x}{@render item(x)}{/each}</ol>{:else}<ul>{#each items as x}{@render item(x)}{/each}</ul>{/if}
	{:else if component.kind === 'record'}
		{@const r = component.props}
		{#if r.title}<h3>{r.title}</h3>{/if}
		{@render deltaBar(r.fields.map((f) => f.delta))}
		<dl>
			{#each r.fields.filter((f) => shownIn(f.delta, view)) as f}
				{@const was = f.delta === 'changed' && f.was !== undefined}
				<dt data-delta={f.delta}>{@render mark(f.delta)}{f.key}</dt>
				<dd>
					{#if view === 'before' && f.delta === 'changed'}
						{#if was}{@render value(f.was, f.key)}{:else}<span class="muted">(dřív neuvedeno)</span>{/if}
					{:else if view === 'changes' && was}
						<span class="old">{@render value(f.was, f.key)}</span> → <span class="new">{@render value(f.value, f.key)}</span>
					{:else}{@render value(f.value, f.key)}{/if}
				</dd>
			{/each}
		</dl>
	{:else if component.kind === 'kpi'}
		<!-- serve's number, one text node; the change is an arrow, a sign and a word, never colour only. -->
		{@const k = component.props}
		<h3>{k.title}</h3>
		<p class="kpi-value">{k.unit ? `${number(k.value)} ${k.unit}` : number(k.value, isMoney(k.title))}</p>
		{#if k.delta !== undefined}
			<p class="kpi-delta">{signed(k.delta)}<span class="sr">{k.delta > 0 ? ' up' : k.delta < 0 ? ' down' : ' unchanged'}</span>{#if k.delta_label}{' '}{k.delta_label}{/if}</p>
		{/if}
		{#if k.source}<p class="muted">{k.source}</p>{/if}
	{:else if component.kind === 'chart'}
		{#if component.props.title}<h3>{component.props.title}</h3>{/if}
		<Chart chart={component.props} />
	{:else if component.kind === 'tree'}
		{@const t = component.props}
		{@const kids = t.nodes[0]?.children?.length ?? 0}
		{@const org = t.nodes.length === 1 && kids >= 2 && kids <= 4}
		{#snippet orgNode(n: TreeNode, parent: Delta | undefined)}
			{@const d = inherit(n.delta, parent)}
			{#if shownIn(d, view)}
				<div class="node" data-delta={d}>
					<span class="label">{@render mark(d)}{n.label}</span>
					{#if n.note}<span class="note">{n.note}</span>{/if}
					{#if n.children?.length}
						<div class="kids">{#each n.children as c}{@render orgNode(c, d)}{/each}</div>
					{/if}
				</div>
			{/if}
		{/snippet}
		{#snippet listNodes(nodes: TreeNode[], parent: Delta | undefined)}
			{#each nodes as n}
				{@const d = inherit(n.delta, parent)}
				{#if shownIn(d, view)}
					<li data-delta={d}>
						{@render mark(d)}{n.label}{#if n.note}<span class="muted"> — {n.note}</span>{/if}
						{#if n.children?.length}<ul>{@render listNodes(n.children, d)}</ul>{/if}
					</li>
				{/if}
			{/each}
		{/snippet}
		{#if t.title}<h3>{t.title}</h3>{/if}
		{@render deltaBar(treeDeltas(t.nodes))}
		{#if org}
			<div class="org" data-layout="org">{@render orgNode(t.nodes[0], undefined)}</div>
		{:else}
			<ul class="tree" data-layout="list">{@render listNodes(t.nodes, undefined)}</ul>
		{/if}
	{:else if component.kind === 'timeline'}
		{#if component.props.title}<h3>{component.props.title}</h3>{/if}
		<Timeline timeline={component.props} />
	{:else if component.kind === 'graph'}
		{#if component.props.title}<h3>{component.props.title}</h3>{/if}
		<Graph graph={component.props} />
	{:else if component.kind === 'sequence'}
		{#if component.props.title}<h3>{component.props.title}</h3>{/if}
		<Sequence sequence={component.props} />
	{:else if component.kind === 'form'}
		<Form form={component.props} />
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
	.query {
		margin: 0 0 6px;
		font-size: 11px;
	}
	table {
		border-collapse: collapse;
		font-size: 12px;
		width: 100%;
	}
	.scroll {
		overflow-x: auto;
	}
	th,
	td {
		text-align: left;
		padding: 3px 8px;
		border-bottom: 1px solid var(--glass-brd);
		white-space: pre-wrap;
		overflow-wrap: break-word;
		min-width: 6ch;
		vertical-align: top;
	}
	th {
		white-space: nowrap;
	}
	tr:has(+ .more) td {
		border-bottom: none;
	}
	.more td {
		padding-top: 0;
	}
	summary {
		cursor: pointer;
		font-size: 11px;
	}
	.field {
		margin: 6px 0;
	}
	.field div {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		line-height: 1.45;
	}
	dl {
		margin: 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 3px 10px;
		font-size: 12px;
	}
	dt {
		font-weight: 600;
	}
	dd {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	pre {
		margin: 0;
		font-family: ui-monospace, monospace;
		white-space: pre-wrap;
	}
	ul,
	ol {
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
	.org {
		display: flex;
		justify-content: center;
	}
	.org .node {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}
	.org .label,
	.org .note {
		border: 1px solid var(--glass-brd);
		border-radius: 6px;
		padding: 2px 8px;
	}
	.org .kids {
		display: flex;
		gap: 12px;
		border-top: 1px solid var(--glass-brd);
		margin-top: 6px;
		padding-top: 8px;
	}
	.kpi-value {
		margin: 4px 0;
		font-size: 32px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.kpi-delta {
		margin: 0;
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
	.mark {
		font-family: ui-monospace, monospace;
		font-weight: 700;
	}
	.mark[data-delta='added'] {
		color: var(--ok-ink);
	}
	.mark[data-delta='removed'] {
		color: var(--bad-ink);
	}
	.mark[data-delta='changed'] {
		color: var(--warn-ink);
	}
	.delta-bar {
		display: flex;
		gap: 10px;
		align-items: center;
		margin: 0 0 6px;
		font-size: 11px;
	}
	.views {
		display: flex;
		gap: 8px;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}
</style>
