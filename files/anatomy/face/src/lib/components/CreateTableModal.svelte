<!--
  CreateTableModal — author a NEW KEAP DataTable (manager+ only; the BFF POST
  re-enforces the tier). Title → auto slug (dash-legal), a columns builder, and
  /explore metadata (description + anchor). All pure logic lives in
  $lib/tables/createtable; this component is the form shell. Escaped text only —
  never {@html}.
-->
<script lang="ts">
	import { tablesCreateTable } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import {
		slugFromTitle,
		validateDraft,
		buildCreateBody,
		defaultColumns,
		CREATE_COLUMN_KINDS,
		type DraftColumn
	} from '$lib/tables/createtable';

	let { oncreated, oncancel }: { oncreated: (slug: string) => void; oncancel: () => void } =
		$props();

	let title = $state('');
	let slug = $state('');
	let slugTouched = $state(false);
	let description = $state('');
	let anchor = $state('');
	let columns = $state<DraftColumn[]>(defaultColumns());
	let submitting = $state(false);
	let err = $state('');

	// Keep slug mirrored from title until the user edits the slug by hand.
	$effect(() => {
		if (!slugTouched) slug = slugFromTitle(title);
	});

	function addColumn() {
		columns = [...columns, { key: '', label: '', kind: 'text', required: false, options: '' }];
	}
	function removeColumn(i: number) {
		if (columns.length <= 1) return;
		columns = columns.filter((_, idx) => idx !== i);
	}

	async function submit() {
		err = '';
		const v = validateDraft(slug, columns);
		if (!title.trim()) {
			err = 'Give the table a title.';
			return;
		}
		if (v) {
			err = v;
			return;
		}
		submitting = true;
		try {
			const body = buildCreateBody({ slug, title, description, anchor, columns });
			await tablesCreateTable(body);
			oncreated(body.slug);
		} catch (e) {
			err = e instanceof ApiError ? e.message : 'could not create table';
		} finally {
			submitting = false;
		}
	}
</script>

<div class="scrim" role="presentation" onclick={oncancel}></div>
<div class="modal">
	<div class="editor glass" role="dialog" aria-label="Create table" tabindex="-1">
		<header class="eh">
			<strong>New DataTable</strong>
			<button class="x" aria-label="Cancel" onclick={oncancel}>✕</button>
		</header>

		<div class="fields">
			<label class="field">
				<span class="lbl">Title <span class="req">*</span></span>
				<input type="text" bind:value={title} placeholder="e.g. Bookmarks" />
			</label>

			<label class="field">
				<span class="lbl">Slug <span class="hint">key · dashes only</span></span>
				<input
					type="text"
					bind:value={slug}
					oninput={() => (slugTouched = true)}
					placeholder="bookmarks"
				/>
			</label>

			<label class="field">
				<span class="lbl">Description</span>
				<textarea
					rows="2"
					bind:value={description}
					placeholder="What this table holds (shown in /explore)"
				></textarea>
			</label>

			<label class="field">
				<span class="lbl">Anchor</span>
				<input type="text" bind:value={anchor} placeholder="e.g. nos.applications" />
				<span class="sub">anchors this table into /explore (optional)</span>
			</label>

			<div class="cols">
				<div class="cols-head">
					<span class="lbl">Columns</span>
					<button class="mini" onclick={addColumn}>＋ Add column</button>
				</div>
				{#each columns as col, i (i)}
					<div class="colrow">
						<input class="ckey" type="text" bind:value={col.key} placeholder="key" />
						<input class="clabel" type="text" bind:value={col.label} placeholder="label" />
						<select class="ckind" bind:value={col.kind}>
							{#each CREATE_COLUMN_KINDS as k (k)}
								<option value={k}>{k}</option>
							{/each}
						</select>
						<label class="creq" title="required">
							<input type="checkbox" bind:checked={col.required} /> req
						</label>
						<button
							class="crm"
							aria-label="Remove column"
							disabled={columns.length <= 1}
							onclick={() => removeColumn(i)}>✕</button
						>
						{#if col.kind === 'select'}
							<input
								class="copts"
								type="text"
								bind:value={col.options}
								placeholder="options, comma, separated"
							/>
						{/if}
					</div>
				{/each}
			</div>
		</div>

		{#if err}<p class="err">{err}</p>{/if}

		<footer class="ef">
			<button class="btn ghost" onclick={oncancel} disabled={submitting}>Cancel</button>
			<button class="btn primary" onclick={submit} disabled={submitting}>
				{submitting ? 'Creating…' : 'Create table'}
			</button>
		</footer>
	</div>
</div>

<style>
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
	.editor {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 14px;
		border-radius: 12px;
		font-size: 13px;
		width: 520px;
		max-width: 92vw;
		background: var(--glass, rgba(20, 26, 40, 0.92));
	}
	.eh {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.x {
		background: none;
		border: none;
		color: var(--muted, #9aa4b2);
		cursor: pointer;
		font-size: 13px;
	}
	.fields {
		display: flex;
		flex-direction: column;
		gap: 10px;
		max-height: 60vh;
		overflow: auto;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
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
	.cols {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.cols-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.mini {
		background: rgba(255, 255, 255, 0.08);
		color: var(--fg, #e8ecf3);
		border: none;
		border-radius: 6px;
		padding: 3px 9px;
		font-size: 11px;
		cursor: pointer;
	}
	.colrow {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.ckey {
		width: 96px;
	}
	.clabel {
		flex: 1;
		min-width: 90px;
	}
	.ckind {
		width: 108px;
	}
	.copts {
		flex-basis: 100%;
	}
	.creq {
		display: flex;
		align-items: center;
		gap: 3px;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.crm {
		background: none;
		border: none;
		color: var(--muted, #9aa4b2);
		cursor: pointer;
	}
	.crm:disabled {
		opacity: 0.35;
		cursor: default;
	}
	input[type='text'],
	select,
	textarea {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.12));
		border-radius: 8px;
		padding: 8px 10px;
		color: var(--fg, #e8ecf3);
		font-size: 13px;
		box-sizing: border-box;
	}
	.field input,
	.field textarea {
		width: 100%;
	}
	textarea {
		resize: vertical;
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
