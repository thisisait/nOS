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
	import { resolveView, orderRows, timelineSections, formatWhen, matchRow } from '$lib/tables/view';
	import { StatusNote, Badge, prefersReducedMotion } from './ui';

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
	const ordered = $derived(data && view ? orderRows(data.rows, view) : []);

	// ── Facets: the two filter levels ────────────────────────────────────────
	//
	// Native `<select>`, not a tab strip: `track` has 7 values and `status` 11,
	// and a shell that has no Menu primitive would otherwise be growing one for
	// a filter. The second level is scoped by the first — that IS the nesting;
	// the declaration stays a flat pair of column keys so a renderer affording
	// only one level can honour `facets[0]` and ignore the rest.
	let picked = $state<Record<string, string>>({});
	// A facet selection belongs to a table, not to the window. Switching tables
	// with `status=blocked` still applied would show an empty list that looks
	// like the table is empty.
	$effect(() => {
		void data?.slug;
		picked = {};
		dismissed = false;
	});

	const cellOf = (row: DataTableRow, key: string): string =>
		row[key] === null || row[key] === undefined ? '' : String(row[key]);

	/** Rows passing every facet ABOVE `level` — what level `level`'s counts are
	 *  computed over, and what makes the second level a refinement of the first. */
	function upTo(level: number): DataTableRow[] {
		if (!view) return ordered;
		return ordered.filter((r) =>
			view.facets.slice(0, level).every((f) => !picked[f.key] || cellOf(r, f.key) === picked[f.key])
		);
	}

	/** Value → count, for one facet, over the rows the levels above left. A value
	 *  with no rows is not offered: a filter that can only empty the list is not
	 *  a choice, it is a trap. */
	function optionsFor(level: number, key: string): [string, number][] {
		const tally = new Map<string, number>();
		for (const r of upTo(level)) {
			const v = cellOf(r, key);
			if (v) tally.set(v, (tally.get(v) ?? 0) + 1);
		}
		return [...tally].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
	}

	const rows = $derived(view ? upTo(view.facets.length) : ordered);

	// ── Highlights: navigation, not decoration ───────────────────────────────
	//
	// Counted over the rows actually on screen, so a click always lands. A
	// highlight matching nothing is DROPPED rather than rendered as a zero —
	// `Badge` already refuses to print a 0, and a strip of empty labels is how a
	// navigation aid stops being read.
	const hits = $derived(
		(view?.highlights ?? [])
			.map((h) => ({ ...h, rows: rows.filter((r) => matchRow(r, h.when)) }))
			.filter((h) => h.rows.length > 0)
	);

	// ── The offer ────────────────────────────────────────────────────────────
	let dismissed = $state(false);
	let root = $state<HTMLDivElement | null>(null);
	let flashed = $state('');

	const offer = $derived(view?.offer ?? null);
	const offerRows = $derived(offer ? rows.filter((r) => matchRow(r, offer.when)) : []);
	const offerRow = $derived(offerRows[0] ?? null);
	const showOffer = $derived(!dismissed && !!offer && !!offerRow);

	const rowDomId = (id: unknown) => `dt-row-${String(id)}`;

	/**
	 * Where the offer sits: at the row it is about.
	 *
	 * `offsetTop` against the positioned `.dt` root, NOT `getBoundingClientRect`
	 * — the offer is inside the scrolling body, so a viewport rectangle would be
	 * correct once and wrong after the first scroll, drag or window resize, and
	 * would need three listeners to stay right. An offset against an ancestor is
	 * layout, and layout already recomputes itself.
	 */
	const offerTop = $derived.by(() => {
		void rows;
		if (!showOffer || !root || !offerRow) return 0;
		const el = root.querySelector<HTMLElement>(`#${CSS.escape(rowDomId(offerRow.id))}`);
		return el ? Math.max(0, el.offsetTop - 6) : 0;
	});

	/** The one action in VIEW_ACTIONS. Scroll to the row and mark it — the offer
	 *  navigates; it does not write, and there is deliberately no arm here that
	 *  could. */
	function focusHighlight(row: DataTableRow | null) {
		if (!row || !root) return;
		const el = root.querySelector<HTMLElement>(`#${CSS.escape(rowDomId(row.id))}`);
		el?.scrollIntoView({
			behavior: prefersReducedMotion() ? 'auto' : 'smooth',
			block: 'center'
		});
		flashed = String(row.id);
		setTimeout(() => (flashed = ''), 1600);
	}
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

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && showOffer) dismissed = true;
	}}
/>

{#if !data || !view}
	<StatusNote kind="empty">No table.</StatusNote>
{:else}
	<div class="dt" bind:this={root}>
		<header class="dt-head">
			<strong>{data.title}</strong>
			{#if data.source === 'fallback'}
				<!-- `warn`, not neutral: repo defaults are not the live catalog, and
				     a quiet marker is how that difference stops being noticed. -->
				<Badge tone="warn" outline title="KEAP unreachable — showing repo defaults">
					offline defaults
				</Badge>
			{/if}
			{#if view.degradedFrom}
				<!-- Say it, rather than rendering an empty article list that looks
				     like the style is working. -->
				<Badge
					tone="warn"
					outline
					title="The declared {view.degradedFrom} view needs a column this table no longer has — showing the grid."
				>
					{view.degradedFrom} view unavailable
				</Badge>
			{/if}
			{#if data.viewDropped?.length}
				<!-- The declared block lost part of itself on the way in. Saying so
				     is the same rule as `degradedFrom`: a half-applied declaration
				     renders as a working one. -->
				<Badge
					tone="warn"
					outline
					count={data.viewDropped.length}
					title="Dropped from the view block (unknown column, op or action): {data.viewDropped.join(
						', '
					)}"
				>
					dropped
				</Badge>
			{/if}
			<span class="spacer"></span>
			{#if data.canWrite}
				<button class="add" onclick={() => open(null)}>＋ Add row</button>
			{/if}
		</header>

		<!-- ── FACETS — two levels, outer→inner ─────────────────────────────── -->
		{#if view.facets.length}
			<div class="facets">
				{#each view.facets as f, level (f.key)}
					{@const opts = optionsFor(level, f.key)}
					<label class="facet">
						<span class="facet-label">{f.label}</span>
						<select bind:value={picked[f.key]}>
							<option value="">All ({upTo(level).length})</option>
							{#each opts as [value, n] (value)}
								<option {value}>{value} ({n})</option>
							{/each}
						</select>
					</label>
				{/each}
				{#if Object.values(picked).some(Boolean)}
					<button class="edit" onclick={() => (picked = {})}>clear</button>
					<span class="when">{rows.length} of {ordered.length}</span>
				{/if}
			</div>
		{/if}

		<!-- ── HIGHLIGHTS — the fast navigation ─────────────────────────────── -->
		{#if hits.length}
			<nav class="highlights" aria-label="Key entries">
				{#each hits as h (h.label)}
					<button
						class="hl"
						type="button"
						onclick={() => focusHighlight(h.rows[0])}
						title="Jump to the first of {h.rows.length}: {heading(h.rows[0])}"
					>
						<Badge tone="info" count={h.rows.length}>{h.label}</Badge>
					</button>
				{/each}
			</nav>
		{/if}

		{#if rows.length === 0 && ordered.length > 0}
			<!-- Filtered to nothing is NOT an empty table, and rendering the same
			     note for both is how a filter starts reading as missing data. -->
			<StatusNote kind="empty">
				No rows match this filter — {ordered.length} in the table.
			</StatusNote>
		{:else if rows.length === 0}
			<StatusNote kind="empty">No rows.</StatusNote>

			<!-- ── GRID ─────────────────────────────────────────────────────
			     `chat` renders here too, DELIBERATELY: the resolver admits the
			     style but this component has no arm for it yet, and the {:else}
			     catch-all below is TILES — so a declared chat was silently
			     rendering as tiles, a style nobody asked for wearing no badge.
			     Until the exchange renderer ships, chat gets the grid: the same
			     target every other unhonourable style degrades to. -->
		{:else if view.style === 'grid' || view.style === 'chat'}
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
							<tr id={rowDomId(row.id)} class:flash={flashed === String(row.id)}>
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
					<article class="post" id={rowDomId(row.id)} class:flash={flashed === String(row.id)}>
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
			<!-- Month headings, not one flat dot-list: a timeline whose time axis
			     is invisible reads as a chat feed, and the undated tail becomes
			     one named bucket ("no Target") instead of a wall of dashes. -->
			<ol class="timeline">
				{#each timelineSections(rows, view) as sec (sec.label)}
					<li class="tl-sec" aria-hidden="true">{sec.label}</li>
					{#each sec.rows as row (row.id)}
					<li id={rowDomId(row.id)} class:flash={flashed === String(row.id)}>
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
				{/each}
			</ol>

			<!-- ── TILES ────────────────────────────────────────────────────── -->
		{:else}
			<div class="tiles">
				{#each rows as row (row.id)}
					<button
						class="tile"
						id={rowDomId(row.id)}
						class:flash={flashed === String(row.id)}
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

		<!-- ── THE OFFER ────────────────────────────────────────────────────
		     Anchored to the row it is about, inside the scrolling body — so it
		     needs no z-band above the shell chrome, no scroll/drag/resize
		     listeners, and it cannot outlive the surface that owns it.
		     `role="status"` because it appears without the user asking. -->
		{#if showOffer && offer}
			<aside class="offer" style="top:{offerTop}px" role="status">
				<span class="offer-text">{offer.label}</span>
				<span class="offer-n">{offerRows.length}</span>
				<button class="offer-go" type="button" onclick={() => focusHighlight(offerRow)}>
					Show
				</button>
				<button
					class="offer-x"
					type="button"
					aria-label="Dismiss suggestion"
					onclick={() => (dismissed = true)}>✕</button
				>
			</aside>
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
		/* The offer's offsetParent. Nothing else depends on it. */
		position: relative;
	}

	/* ── facets + highlights + offer ───────────────────────────────────── */
	.facets {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
	}
	.facet {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.facet-label {
		color: var(--muted, #9aa4b2);
		font-size: 11px;
	}
	.facet select {
		background: rgba(255, 255, 255, 0.06);
		color: var(--fg, #e8ecf3);
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.1));
		border-radius: 7px;
		padding: 3px 7px;
		font: inherit;
		font-size: 12px;
	}
	.highlights {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.hl {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font: inherit;
	}
	.hl:focus-visible {
		outline: 2px solid rgba(90, 150, 255, 0.8);
		outline-offset: 2px;
		border-radius: 999px;
	}
	.offer {
		position: absolute;
		right: 0;
		display: flex;
		align-items: center;
		gap: 8px;
		max-width: min(340px, 90%);
		padding: 7px 9px;
		border-radius: 10px;
		background: rgba(24, 30, 42, 0.92);
		border: 1px solid rgba(90, 150, 255, 0.35);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
		font-size: 12px;
		backdrop-filter: blur(6px);
	}
	.offer-text {
		overflow-wrap: anywhere;
	}
	.offer-n {
		flex: none;
		color: var(--muted, #9aa4b2);
		font-variant-numeric: tabular-nums;
	}
	.offer-go {
		flex: none;
		background: rgba(90, 150, 255, 0.85);
		color: #fff;
		border: none;
		border-radius: 7px;
		padding: 3px 10px;
		font: inherit;
		font-size: 11px;
		cursor: pointer;
	}
	.offer-x {
		flex: none;
		background: none;
		border: none;
		color: var(--muted, #9aa4b2);
		cursor: pointer;
		font-size: 12px;
		line-height: 1;
	}
	/* The landing mark. `focus-highlight` scrolls; without this the row it
	   scrolled to is indistinguishable from the four around it. */
	.flash {
		animation: flash 1.6s ease-out;
	}
	@keyframes flash {
		from {
			background: rgba(90, 150, 255, 0.22);
		}
		to {
			background: transparent;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.flash {
			animation: none;
			outline: 2px solid rgba(90, 150, 255, 0.7);
		}
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
	/* .badge / .badge.warn / .muted removed 2026-08-05 — they are
	   $lib/components/ui now, so this component's "offline defaults" marker no
	   longer has its own private amber. */
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
	/* Month heading. No dot, no rail — it is an axis label, not an entry. */
	.timeline li.tl-sec {
		display: block;
		padding: 6px 0 10px 21px;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted, #9aa4b2);
	}
	.timeline li.tl-sec::before {
		display: none;
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
