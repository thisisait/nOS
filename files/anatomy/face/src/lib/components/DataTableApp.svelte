<script lang="ts">
	/**
	 * Generic DataTable renderer (rawDataTable surface).
	 *
	 * Renders a `DataTable` (columns + rows) as a plain table with per-row cell
	 * display. Every value goes through Svelte's `{expr}` auto-escaping — there is
	 * NO `{@html}` here and there must never be (Wave-2 XSS gate). Cell values of
	 * unknown shape are stringified defensively.
	 */
	import type { DataTable, DataTableRow, ColumnSpec } from '$lib/contracts';

	let { table }: { table: DataTable | null } = $props();

	/** Coerce an arbitrary cell value into a display string (auto-escaped by the
	 *  template). Objects/arrays render as compact JSON. */
	function cell(row: DataTableRow, col: ColumnSpec): string {
		const v = row[col.key];
		if (v === null || v === undefined) return '';
		if (typeof v === 'boolean') return v ? '✓' : '—';
		if (typeof v === 'object') {
			try {
				return JSON.stringify(v);
			} catch {
				return String(v);
			}
		}
		return String(v);
	}
</script>

{#if !table}
	<p class="muted">No table.</p>
{:else}
	<div class="dt">
		<header class="dt-head">
			<strong>{table.title}</strong>
			{#if table.source === 'fallback'}
				<span class="badge" title="KEAP unreachable — showing repo defaults">offline defaults</span>
			{/if}
		</header>

		{#if table.rows.length === 0}
			<p class="muted">No rows.</p>
		{:else}
			<div class="scroll">
				<table>
					<thead>
						<tr>
							{#each table.columns as col (col.key)}
								<th>{col.label}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each table.rows as row (row.id)}
							<tr>
								{#each table.columns as col (col.key)}
									<td>{cell(row, col)}</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
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
</style>
