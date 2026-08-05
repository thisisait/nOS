<!--
  TablesApp — a first-class DataTable browser + editor (Tier F1).

  Left: every table in KEAP (listTables → GET /bff/tables?op=list). Right: the
  selected table's rows in the editable grid (DataTableApp → the raw editable
  view; Add/Edit gated server-side by `table.canWrite`). Schema-driven +
  table-agnostic: works for face-* config tables and any future Apps/Systems
  tables. All values render escaped ({expr}) — never {@html}.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { listTables, loadTable } from '$lib/api/tables';
	import type { TableSummary } from '$lib/tables/summary';
	import type { DataTable } from '$lib/contracts';
	import DataTableApp from '$lib/components/DataTableApp.svelte';
	import CreateTableModal from '$lib/components/CreateTableModal.svelte';
	import { StatusNote } from '$lib/components/ui';

	let tables = $state<TableSummary[]>([]);
	let loadingList = $state(true);
	let listErr = $state('');
	let selected = $state<string | null>(null);
	let table = $state<DataTable | null>(null);
	let loadingTable = $state(false);
	let tableErr = $state('');
	let canCreate = $state(false);
	let creating = $state(false);

	onMount(async () => {
		// Non-blocking: whether the New-table button shows (BFF re-enforces the tier).
		void fetch('/bff/config', { headers: { accept: 'application/json' } })
			.then((r) => (r.ok ? r.json() : null))
			.then((b: { canWriteTables?: boolean } | null) => {
				canCreate = b?.canWriteTables === true;
			})
			.catch(() => {});
		try {
			tables = await listTables();
			if (tables.length > 0) void select(tables[0].slug);
		} catch (e) {
			listErr = e instanceof Error ? e.message : 'could not list tables';
		} finally {
			loadingList = false;
		}
	});

	async function onCreated(slug: string) {
		creating = false;
		try {
			tables = await listTables();
		} catch {
			/* keep current list */
		}
		void select(slug);
	}

	async function select(slug: string) {
		selected = slug;
		loadingTable = true;
		tableErr = '';
		table = null;
		try {
			table = await loadTable(slug);
		} catch (e) {
			tableErr = e instanceof Error ? e.message : 'could not load table';
		} finally {
			loadingTable = false;
		}
	}
</script>

<div class="tables">
	<aside class="side">
		<div class="side-head">
			<span>Tables</span>
			{#if canCreate}
				<button class="new" onclick={() => (creating = true)}>＋ New</button>
			{/if}
		</div>
		{#if loadingList}
			<StatusNote kind="loading" block={false}>loading…</StatusNote>
		{:else if listErr}
			<StatusNote kind="error" block={false}>{listErr}</StatusNote>
		{:else if tables.length === 0}
			<StatusNote kind="empty" block={false}>No tables in KEAP yet.</StatusNote>
		{:else}
			<ul>
				{#each tables as t (t.slug)}
					<li>
						<button class="t" class:sel={selected === t.slug} onclick={() => select(t.slug)}>
							<span class="nm">{t.title}</span>
							<span class="ct">{t.rowCount}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</aside>

	<section class="main">
		{#if loadingTable}
			<StatusNote kind="loading">loading table…</StatusNote>
		{:else if tableErr}
			<StatusNote kind="error">{tableErr}</StatusNote>
		{:else if table}
			{#key table.slug}
				<DataTableApp {table} />
			{/key}
		{:else}
			<p class="muted">Select a table.</p>
		{/if}
	</section>
</div>

{#if creating}
	<CreateTableModal oncreated={onCreated} oncancel={() => (creating = false)} />
{/if}

<style>
	.tables {
		display: flex;
		height: 100%;
		gap: 10px;
		min-height: 0;
	}
	.side {
		width: 200px;
		flex-shrink: 0;
		border-right: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.1));
		padding-right: 8px;
		overflow: auto;
	}
	.side-head {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted, #9aa4b2);
		margin: 2px 4px 8px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
	}
	.new {
		background: rgba(90, 150, 255, 0.85);
		color: #fff;
		border: none;
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 10px;
		letter-spacing: 0;
		text-transform: none;
		cursor: pointer;
	}
	.side ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.t {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 8px;
		background: none;
		border: none;
		color: var(--fg, #e8ecf3);
		padding: 7px 9px;
		border-radius: 8px;
		text-align: left;
		cursor: pointer;
		font-size: 13px;
	}
	.t:hover {
		background: rgba(255, 255, 255, 0.06);
	}
	.t.sel {
		background: rgba(90, 150, 255, 0.22);
	}
	.nm {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ct {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		font-variant-numeric: tabular-nums;
	}
	.main {
		flex: 1;
		min-width: 0;
		overflow: auto;
	}
	.muted {
		color: var(--muted, #9aa4b2);
		font-size: 13px;
	}
	/* .err removed 2026-08-05 — errors are StatusNote now, so this app no
	   longer has its own shade of red. */
</style>
