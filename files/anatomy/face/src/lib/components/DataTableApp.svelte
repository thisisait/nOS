<script lang="ts">
	/**
	 * Generic DataTable renderer + editor (rawDataTable surface).
	 *
	 * FOUR STYLES over one resolve step. The table itself declares which one it
	 * wants (KEAP `view` block); `resolveView` picks the columns and degrades to
	 * the grid when a declared style cannot be honoured. Before this there was
	 * only the grid, and the grid sets `white-space: nowrap` — correct for a
	 * status column, useless for a `research` column holding three paragraphs,
	 * which is exactly the table this was built for.
	 *
	 * Every value goes through Svelte's `{expr}` auto-escaping — NO `{@html}`
	 * (Wave-2 XSS gate). That is why the blog body renders as pre-wrapped text
	 * and not as markdown: rendering author-supplied markup here would need a
	 * sanitiser, and the gate is the cheaper guarantee.
	 */
	import type { DataTable, DataTableRow, ColumnSpec } from '$lib/contracts';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import RowEditor from './RowEditor.svelte';
	import { resolveView, orderRows, formatWhen } from '$lib/tables/view';

	let { table }: { table: DataTable | null } = $props();

	// Local, refreshable copy so a write can re-pull rows without the parent.
	let data = $state<DataTable | null>(null);
	$effect(() => {
		data = table;
	});

	let editing = $state<{ row: DataTableRow | null } | null>(null);
	let submitting = $state(false);
	let saveErr = $state('');

	const view = $derived(data ? resolveView(data) : null);
	const rows = $derived(data && view ? orderRows(data.rows, view) : []);
	/** Grid columns: everything. The other styles claim specific columns and
	 *  show the rest only inside the editor — a card that reprinted all 23
	 *  columns would be a grid with rounded corners. */
	const gridCols = $derived(data?.columns ?? []);

	function cell(row: DataTableRow, col: ColumnSpec): string {
		const v = row[col.key];
		if (v === null || v === undefined) return '';
		if (typeof v === 'boolean') return v ? '✓' : '—';
		if (col.kind === 'vector') return '⋯'; // brain-embedding — not shown inline
		if (typeof v === 'object') {
			try {
				return JSON.stringify(v);
			} catch {
				return String(v);
			}
		}
		return String(v);
	}

	/** Heading for a card/entry. Falls back to the row id so an untitled row is
	 *  still clickable rather than an invisible strip. */
	function heading(row: DataTableRow): string {
		const t = view?.title ? cell(row, view.title) : '';
		return t || `row ${String(row.id ?? '').slice(0, 8)}`;
	}

	function mediaUrl(row: DataTableRow): string {
		if (!view?.media) return '';
		const v = row[view.media.key];
		if (typeof v === 'string') return v;
		if (v && typeof v === 'object' && 'url' in v) return String((v as { url: unknown }).url ?? '');
		return '';
	}

	function open(row: DataTableRow | null) {
		saveErr = '';
		editing = { row };
	}

	async function refresh() {
		if (!data) return;
		try {
			data = await loadTable(data.slug);
		} catch {
			/* keep current rows on a transient error */
		}
	}

	async function save(row: Record<string, unknown>) {
		if (!data) return;
		submitting = true;
		saveErr = '';
		try {
			await tablesUpsertRow(data.slug, row);
			await refresh();
			editing = null;
		} catch (e) {
			saveErr = e instanceof ApiError ? e.message : 'save failed';
		} finally {
			submitting = false;
		}
	}
</script>

{#if !data || !view}
	<p class="muted">No table.</p>
{:else}
	<div class="dt">
		<header class="dt-head">
			<strong>{data.title}</strong>
			{#if data.source === 'fallback'}
				<span class="badge" title="KEAP unreachable — showing repo defaults">offline defaults</span>
			{/if}
			{#if view.degradedFrom}
				<!-- Say it, rather than rendering an empty article list that looks
				     like the style is working. -->
				<span
					class="badge warn"
					title="The declared {view.degradedFrom} view needs a column this table no longer has — showing the grid."
					>{view.degradedFrom} view unavailable</span
				>
			{/if}
			<span class="spacer"></span>
			{#if data.canWrite}
				<button class="add" onclick={() => open(null)}>＋ Add row</button>
			{/if}
		</header>

		{#if rows.length === 0}
			<p class="muted">No rows.</p>

			<!-- ── GRID ─────────────────────────────────────────────────────── -->
		{:else if view.style === 'grid'}
			<div class="scroll">
				<table>
					<thead>
						<tr>
							{#each gridCols as col (col.key)}
								<th>{col.label}</th>
							{/each}
							{#if data.canWrite}<th class="edit-col"></th>{/if}
						</tr>
					</thead>
					<tbody>
						{#each rows as row (row.id)}
							<tr>
								{#each gridCols as col (col.key)}
									<td>{cell(row, col)}</td>
								{/each}
								{#if data.canWrite}
									<td class="edit-col">
										<button class="edit" aria-label="Edit row" onclick={() => open(row)}
											>edit</button
										>
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- ── BLOG ─────────────────────────────────────────────────────── -->
		{:else if view.style === 'blog'}
			<div class="feed">
				{#each rows as row (row.id)}
					<article class="post">
						<h3>{heading(row)}</h3>
						{#if view.meta.length || view.date}
							<p class="meta">
								{#if view.date}<span class="when">{formatWhen(row[view.date.key])}</span>{/if}
								{#each view.meta as m (m.key)}
									<span class="chip">{m.label}: {cell(row, m)}</span>
								{/each}
							</p>
						{/if}
						{#if view.body}
							<!-- pre-wrap, NOT {@html}: the XSS gate forbids author markup here. -->
							<p class="body">{cell(row, view.body)}</p>
						{/if}
						{#if data.canWrite}
							<button class="edit" onclick={() => open(row)}>edit</button>
						{/if}
					</article>
				{/each}
			</div>

			<!-- ── TIMELINE ─────────────────────────────────────────────────── -->
		{:else if view.style === 'timeline'}
			<ol class="timeline">
				{#each rows as row (row.id)}
					<li>
						<span class="dot" aria-hidden="true"></span>
						<div class="entry">
							<p class="when">{view.date ? formatWhen(row[view.date.key]) : '—'}</p>
							<h4>{heading(row)}</h4>
							{#if view.meta.length}
								<p class="meta">
									{#each view.meta as m (m.key)}
										<span class="chip">{cell(row, m)}</span>
									{/each}
								</p>
							{/if}
							{#if view.body}<p class="body clamp">{cell(row, view.body)}</p>{/if}
							{#if data.canWrite}
								<button class="edit" onclick={() => open(row)}>edit</button>
							{/if}
						</div>
					</li>
				{/each}
			</ol>

			<!-- ── TILES ────────────────────────────────────────────────────── -->
		{:else}
			<div class="tiles">
				{#each rows as row (row.id)}
					<button
						class="tile"
						onclick={() => data?.canWrite && open(row)}
						disabled={!data.canWrite}
						type="button"
					>
						{#if mediaUrl(row)}
							<img src={mediaUrl(row)} alt="" loading="lazy" />
						{:else}
							<span class="tile-glyph" aria-hidden="true">▦</span>
						{/if}
						<span class="tile-title">{heading(row)}</span>
						{#if view.meta.length}
							<span class="tile-meta">
								{#each view.meta as m (m.key)}<span class="chip">{cell(row, m)}</span>{/each}
							</span>
						{/if}
					</button>
				{/each}
			</div>
		{/if}
	</div>

	{#if editing}
		<div class="scrim" role="presentation" onclick={() => (editing = null)}></div>
		<div class="modal">
			<RowEditor
				table={data}
				row={editing.row}
				bodyColumn={view.body?.key}
				{submitting}
				error={saveErr}
				onsubmit={save}
				oncancel={() => (editing = null)}
			/>
		</div>
	{/if}
{/if}

<style>
	.dt {
		display: flex;
		flex-direction: column;
		gap: 10px;
		font-size: 13px;
	}
	.dt-head {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.spacer {
		flex: 1;
	}
	.add {
		background: rgba(90, 150, 255, 0.85);
		color: #fff;
		border: none;
		border-radius: 8px;
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
	}
	.edit {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg, #e8ecf3);
		border: none;
		border-radius: 6px;
		padding: 3px 9px;
		font-size: 11px;
		cursor: pointer;
		align-self: flex-start;
	}
	.edit-col {
		text-align: right;
	}
	.badge {
		font-size: 11px;
		padding: 1px 7px;
		border-radius: 999px;
		background: rgba(255, 200, 90, 0.16);
		color: #ffcf7a;
	}
	.badge.warn {
		background: rgba(255, 120, 120, 0.16);
		color: #ff9a9a;
	}
	.scroll {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		width: 100%;
	}
	th,
	td {
		text-align: left;
		padding: 6px 10px;
		border-bottom: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.1));
		white-space: nowrap;
	}
	th {
		color: var(--muted, #9aa4b2);
		font-weight: 600;
	}
	.muted {
		color: var(--muted, #9aa4b2);
	}

	/* ── shared card furniture ─────────────────────────────────────────── */
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
		color: var(--muted, #9aa4b2);
		font-size: 11px;
	}
	.chip {
		padding: 1px 7px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.07);
	}
	.when {
		color: var(--muted, #9aa4b2);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	/* The whole point of the non-grid styles: long text WRAPS. */
	.body {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		line-height: 1.55;
		color: var(--fg, #e8ecf3);
	}
	.clamp {
		display: -webkit-box;
		-webkit-line-clamp: 4;
		line-clamp: 4;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	/* ── blog ──────────────────────────────────────────────────────────── */
	.feed {
		display: flex;
		flex-direction: column;
		gap: 14px;
		max-width: 68ch; /* a measure that is actually readable */
	}
	.post {
		display: flex;
		flex-direction: column;
		gap: 7px;
		padding: 12px 14px;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.035);
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.09));
	}
	.post h3 {
		margin: 0;
		font-size: 15px;
		font-weight: 650;
		letter-spacing: -0.01em;
	}

	/* ── timeline ──────────────────────────────────────────────────────── */
	.timeline {
		list-style: none;
		margin: 0;
		padding: 0 0 0 4px;
		display: flex;
		flex-direction: column;
	}
	.timeline li {
		position: relative;
		display: flex;
		gap: 12px;
		padding: 0 0 16px 0;
	}
	/* The rail: a border on the marker column, stopped by the last item. */
	.timeline li::before {
		content: '';
		position: absolute;
		left: 4px;
		top: 12px;
		bottom: 0;
		width: 1px;
		background: var(--glass-brd, rgba(255, 255, 255, 0.14));
	}
	.timeline li:last-child::before {
		display: none;
	}
	.dot {
		flex: none;
		width: 9px;
		height: 9px;
		margin-top: 5px;
		border-radius: 50%;
		background: rgba(90, 150, 255, 0.9);
		box-shadow: 0 0 0 3px rgba(90, 150, 255, 0.16);
	}
	.entry {
		display: flex;
		flex-direction: column;
		gap: 5px;
		min-width: 0;
		max-width: 68ch;
	}
	.entry h4 {
		margin: 0;
		font-size: 14px;
		font-weight: 620;
	}

	/* ── tiles ─────────────────────────────────────────────────────────── */
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 12px;
	}
	.tile {
		display: flex;
		flex-direction: column;
		gap: 7px;
		padding: 10px;
		text-align: left;
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.035);
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.09));
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.tile:disabled {
		cursor: default;
	}
	.tile img {
		width: 100%;
		aspect-ratio: 16 / 10;
		object-fit: cover;
		border-radius: 8px;
		background: rgba(0, 0, 0, 0.25);
	}
	.tile-glyph {
		display: grid;
		place-items: center;
		aspect-ratio: 16 / 10;
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.04);
		color: var(--muted, #9aa4b2);
		font-size: 26px;
	}
	.tile-title {
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.tile-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}

	.scrim {
		position: fixed;
		inset: 0;
		z-index: 200000;
		background: rgba(0, 0, 0, 0.4);
	}
	.modal {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		z-index: 200001;
	}
</style>
