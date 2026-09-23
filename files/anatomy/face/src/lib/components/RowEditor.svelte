<!--
  RowEditor — column-type-aware form for adding/editing a DataTable row.

  Renders one input per editable column (vector columns are Pulse-generated and
  omitted). On submit it coerces values by kind, validates required cells + the
  stable key, and calls onsubmit(row) with the flat cell bag. All labels/values
  render as escaped text ({…}) — never {@html}.
-->
<script lang="ts">
	import type { DataTable, DataTableRow, ColumnSpec } from '$lib/contracts';
	import { editableColumns, rowKeyColumn, buildRow, validateRow } from './rowedit';

	let {
		table,
		row = null,
		bodyColumn = undefined,
		submitting = false,
		error = '',
		onsubmit,
		oncancel
	}: {
		table: DataTable;
		row?: DataTableRow | null;
		/** The column the table's view block calls its long-form body. It gets a
		 *  prose textarea instead of a one-line input — editing three paragraphs
		 *  through a 13px single-line field is the same defect as rendering them
		 *  in a nowrap grid cell, one step earlier. */
		bodyColumn?: string;
		submitting?: boolean;
		error?: string;
		onsubmit: (row: Record<string, unknown>) => void;
		oncancel: () => void;
	} = $props();

	const cols = $derived(editableColumns(table.columns));
	const keyKey = $derived(rowKeyColumn(table.columns)?.key ?? '');
	const isEdit = $derived(row !== null);

	// Seed form values from an existing row (edit) or empty (add). JSON cells are
	// serialized to a string for the textarea.
	function seed(): Record<string, unknown> {
		const v: Record<string, unknown> = {};
		for (const c of cols) {
			const raw = row ? row[c.key] : undefined;
			if (c.kind === 'json') {
				v[c.key] =
					raw === undefined || raw === null
						? ''
						: typeof raw === 'string'
							? raw
							: JSON.stringify(raw, null, 2);
			} else if (c.kind === 'boolean') {
				v[c.key] = raw === true || raw === 'true';
			} else {
				v[c.key] = raw === undefined || raw === null ? '' : String(raw);
			}
		}
		return v;
	}
	let values = $state<Record<string, unknown>>(seed());
	let localErr = $state('');

	function inputType(col: ColumnSpec): string {
		if (col.kind === 'number') return 'number';
		if (col.kind === 'date') return 'date';
		return 'text';
	}

	function submit() {
		localErr = '';
		const err = validateRow(table.columns, values);
		if (err) {
			localErr = err;
			return;
		}
		onsubmit(buildRow(table.columns, values));
	}
</script>

<!-- Chrome (title, ✕, scrim, sizing, scrolling) belongs to ui/Modal — this is
     only the FORM. It used to carry its own dialog header + 460px cap + inner
     52vh scroll, which is exactly the overflow the shared Modal replaced. -->
<div class="editor">
	<div class="fields">
		{#each cols as col (col.key)}
			<label class="field">
				<span class="lbl">
					{col.label}
					{#if col.required}<span class="req">*</span>{/if}
					{#if col.key === keyKey}<span class="hint">key{isEdit ? ' · locked' : ''}</span>{/if}
				</span>

				{#if col.kind === 'boolean'}
					<input type="checkbox" bind:checked={values[col.key] as boolean} />
				{:else if col.kind === 'select'}
					<select bind:value={values[col.key]}>
						<option value="">—</option>
						{#each col.options ?? [] as opt (opt)}
							<option value={opt}>{opt}</option>
						{/each}
					</select>
				{:else if col.kind === 'json'}
					<textarea rows="4" spellcheck="false" placeholder="JSON" bind:value={values[col.key]}
					></textarea>
				{:else if col.key === bodyColumn && col.kind === 'text'}
					<textarea class="prose" rows="10" spellcheck="true" bind:value={values[col.key]}
					></textarea>
				{:else}
					<input
						type={inputType(col)}
						bind:value={values[col.key]}
						disabled={isEdit && col.key === keyKey}
						placeholder={col.kind === 'taxonomyRef' ? 'anchor id' : ''}
					/>
					{#if col.kind === 'taxonomyRef'}<span class="sub">anchors this row into /explore</span
						>{/if}
				{/if}
			</label>
		{/each}
	</div>

	{#if localErr || error}<p class="err">{localErr || error}</p>{/if}

	<footer class="ef">
		<button class="btn ghost" onclick={oncancel} disabled={submitting}>Cancel</button>
		<button class="btn primary" onclick={submit} disabled={submitting}>
			{submitting ? 'Saving…' : isEdit ? 'Save' : 'Add row'}
		</button>
	</footer>
</div>

<style>
	.editor {
		display: flex;
		flex-direction: column;
		gap: 12px;
		font-size: 13px;
	}
	/* Short fields flow into columns on a wide modal; long-form ones (JSON,
	   prose body) span the full row below. Width and scrolling are Modal's. */
	.fields {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: 10px 14px;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.field:has(textarea) {
		grid-column: 1 / -1;
	}
	.lbl {
		color: var(--muted, #9aa4b2);
		font-size: 12px;
		display: flex;
		gap: 6px;
		align-items: center;
	}
	.req {
		color: #ff8080;
	}
	.hint {
		font-size: 10px;
		padding: 0 6px;
		border-radius: 999px;
		background: rgba(90, 150, 255, 0.2);
		color: #9ec1ff;
	}
	.sub {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	input[type='text'],
	input[type='number'],
	input[type='date'],
	select,
	textarea {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.12));
		border-radius: 8px;
		padding: 8px 10px;
		color: var(--fg, #e8ecf3);
		font-size: 13px;
		width: 100%;
		box-sizing: border-box;
	}
	input:disabled {
		opacity: 0.6;
	}
	textarea {
		resize: vertical;
		font-family: ui-monospace, monospace;
	}
	/* The body field is PROSE, not a payload: readable face, generous leading,
	   and it wraps. The monospace default is right for JSON and wrong here. */
	textarea.prose {
		font-family: inherit;
		font-size: 13.5px;
		line-height: 1.6;
		min-height: 180px;
	}
	.err {
		color: #ff8080;
		font-size: 12px;
		margin: 0;
	}
	.ef {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.btn {
		border: none;
		border-radius: 8px;
		padding: 7px 14px;
		cursor: pointer;
		font-size: 13px;
	}
	.btn.ghost {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg, #e8ecf3);
	}
	.btn.primary {
		background: rgba(90, 150, 255, 0.9);
		color: #fff;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
