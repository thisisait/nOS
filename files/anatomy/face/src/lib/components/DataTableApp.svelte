<script lang="ts">
	/**
	 * Generic DataTable renderer + editor (rawDataTable surface).
	 *
	 * Renders a `DataTable` (columns + rows) and — when the caller may write
	 * (`table.canWrite`, decided server-side by tier) — a gated Add/Edit path via
	 * RowEditor → tablesUpsertRow → refresh. Every value goes through Svelte's
	 * `{expr}` auto-escaping — NO `{@html}` (Wave-2 XSS gate).
	 */
	import type { DataTable, DataTableRow, ColumnSpec } from '$lib/contracts';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import RowEditor from './RowEditor.svelte';

	let { table }: { table: DataTable | null } = $props();

	// Local, refreshable copy so a write can re-pull rows without the parent.
	// Seeded/synced from the prop via the effect (not the initializer) so an
	// in-component refresh() can replace it without the parent re-passing.
	let data = $state<DataTable | null>(null);
	$effect(() => {
		data = table;
	});

	let editing = $state<{ row: DataTableRow | null } | null>(null);
	let submitting = $state(false);
	let saveErr = $state('');

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

{#if !data}
	<p class="muted">No table.</p>
{:else}
	<div class="dt">
		<header class="dt-head">
			<strong>{data.title}</strong>
			{#if data.source === 'fallback'}
				<span class="badge" title="KEAP unreachable — showing repo defaults">offline defaults</span>
			{/if}
			<span class="spacer"></span>
			{#if data.canWrite}
				<button
					class="add"
					onclick={() => {
						saveErr = '';
						editing = { row: null };
					}}>＋ Add row</button
				>
			{/if}
		</header>

		{#if data.rows.length === 0}
			<p class="muted">No rows.</p>
		{:else}
			<div class="scroll">
				<table>
					<thead>
						<tr>
							{#each data.columns as col (col.key)}
								<th>{col.label}</th>
							{/each}
							{#if data.canWrite}<th class="edit-col"></th>{/if}
						</tr>
					</thead>
					<tbody>
						{#each data.rows as row (row.id)}
							<tr>
								{#each data.columns as col (col.key)}
									<td>{cell(row, col)}</td>
								{/each}
								{#if data.canWrite}
									<td class="edit-col">
										<button
											class="edit"
											aria-label="Edit row"
											onclick={() => {
												saveErr = '';
												editing = { row };
											}}>edit</button
										>
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>

	{#if editing}
		<div class="scrim" role="presentation" onclick={() => (editing = null)}></div>
		<div class="modal">
			<RowEditor
				table={data}
				row={editing.row}
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
