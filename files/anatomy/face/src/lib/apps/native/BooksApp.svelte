<!--
  Books — consulting-firm accounting in face (queue, invoices, parties).

  Tables stay the books fallback. CRM SoT is Dolibarr (role not yet in-tree).
  Espo hub tiles remain only while a leftover container is still catalogued.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { vfsDownloadUrl } from '$lib/api/vfs';
	import { hubApps } from '$lib/api/hub';
	import { ApiError } from '$lib/api/client';
	import type { DataTable, DataTableRow, HubApp } from '$lib/contracts';
	import { Tabs, StatusNote, Modal, type TabSpec } from '$lib/components/ui';
	import { openWindow, focusApp } from '$lib/stores/desktop';

	const tabs: TabSpec[] = [
		{ key: 'queue', label: 'Queue' },
		{ key: 'invoices', label: 'Invoices' },
		{ key: 'journals', label: 'Journals' },
		{ key: 'parties', label: 'Parties' }
	];
	let active = $state('queue');
	let queue = $state<DataTable | null>(null);
	let invoices = $state<DataTable | null>(null);
	let journals = $state<DataTable | null>(null);
	let parties = $state<DataTable | null>(null);
	let lines = $state<DataTable | null>(null);
	let postings = $state<DataTable | null>(null);
	/* One row's detail, in the shared Modal. Kind picks what rides along:
	   an invoice brings its lines, a journal its postings, a party its cells. */
	let detail = $state<{ kind: 'invoice' | 'journal' | 'party'; row: DataTableRow } | null>(null);
	let err = $state('');
	let busy = $state('');
	let crm = $state<HubApp | null>(null);
	let bookOwner = $state('');

	onMount(async () => {
		try {
			const [q, i, j, p, ln, po, hub] = await Promise.all([
				loadTable('pending-invoice-verify'),
				loadTable('invoice'),
				loadTable('journal-entry'),
				loadTable('party'),
				loadTable('invoice-line'),
				loadTable('posting').catch(() => null),
				hubApps().catch(() => [] as HubApp[])
			]);
			queue = q;
			invoices = i;
			journals = j;
			parties = p;
			lines = ln;
			postings = po;
			crm = hub.find((a) => a.slug === 'dolibarr') ?? hub.find((a) => a.slug === 'espocrm') ?? null;
		} catch (e) {
			err = e instanceof Error ? e.message : 'could not load books';
		}
	});

	function cell(row: DataTableRow, key: string): string {
		const v = row[key];
		if (v === null || v === undefined) return '';
		return String(v);
	}

	/* The slug of the row whose evidence is open. Approve/Reject live ONLY in
	   the open detail: a verdict without the source next to it is a rubber
	   stamp (operator, 2026-09-23). */
	let openSlug = $state('');

	interface FieldRow {
		key: string;
		value: string;
		confidence: string;
	}
	function fieldRows(row: DataTableRow): FieldRow[] {
		let f: unknown = row.fields;
		if (typeof f === 'string') {
			try {
				f = JSON.parse(f);
			} catch {
				return [];
			}
		}
		if (!f || typeof f !== 'object') return [];
		return Object.entries(f as Record<string, unknown>).map(([key, v]) => {
			const d = v && typeof v === 'object' ? (v as Record<string, unknown>) : { value: v };
			return {
				key,
				value: typeof d.value === 'object' ? JSON.stringify(d.value) : String(d.value ?? ''),
				/* 0 is the pipeline's honest "no per-field confidence yet" (the
				   transport carries no logprobs) — showing a zero everywhere
				   reads as "everything is wrong", so it renders as n/a. */
				confidence:
					d.confidence === undefined || Number(d.confidence) === 0 ? 'n/a' : String(d.confidence)
			};
		});
	}

	function sourceKind(path: string): 'image' | 'pdf' | 'none' {
		if (!path) return 'none';
		const p = path.toLowerCase();
		if (p.endsWith('.pdf')) return 'pdf';
		return 'image';
	}

	async function resolveRow(row: DataTableRow, resolution: 'approved' | 'rejected') {
		if (!queue?.canWrite) return;
		busy = String(row.id);
		err = '';
		try {
			/* Strip the server's own row metadata (__sharing, __id, …) — echoing
			   it back is "unknown column"; and estate date columns hold EPOCH
			   SECONDS, never an ISO string (both measured on the first live
			   Approve, 2026-09-23). */
			const next: Record<string, unknown> = {};
			for (const [k, v] of Object.entries(row)) {
				if (!k.startsWith('__') && k !== 'id') next[k] = v;
			}
			next.resolution = resolution;
			next.resolved_at = Math.floor(Date.now() / 1000);
			if (!next.slug) next.slug = row.id;
			await tablesUpsertRow('pending-invoice-verify', next);
			queue = await loadTable('pending-invoice-verify');
		} catch (e) {
			err = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'upsert failed';
		} finally {
			busy = '';
		}
	}

	function openCrm() {
		if (!crm) return;
		if (!focusApp(crm.slug)) {
			openWindow({
				app: crm.slug,
				title: crm.title,
				w: 720,
				h: 480,
				url: crm.url,
				embed: crm.embed
			});
		}
	}

	const pending = $derived(
		(queue?.rows ?? []).filter((r) => {
			const res = cell(r, 'resolution');
			return res === 'pending' || res === '';
		})
	);

	const owners = $derived(
		[
			...new Set(
				[
					...(invoices?.rows ?? []).map((r) => cell(r, 'book_owner')),
					...(parties?.rows ?? []).map((r) => cell(r, 'slug'))
				].filter(Boolean)
			)
		].sort()
	);

	const shownInvoices = $derived(
		(invoices?.rows ?? []).filter((r) => !bookOwner || cell(r, 'book_owner') === bookOwner)
	);

	const invoiceSlugs = $derived(new Set(shownInvoices.map((r) => String(r.id))));

	const shownJournals = $derived(
		(journals?.rows ?? []).filter((r) => {
			if (!bookOwner) return true;
			const src = cell(r, 'source') || cell(r, 'source__ref');
			return invoiceSlugs.has(src);
		})
	);

	const shownParties = $derived(
		(parties?.rows ?? []).filter((r) => !bookOwner || cell(r, 'slug') === bookOwner)
	);

	/* ── Detail helpers (the modal's content) ─────────────────────────────── */

	/** Every business cell of a row, for a generic key/value detail. */
	function rowCells(row: DataTableRow): { key: string; value: string }[] {
		return Object.entries(row)
			.filter(
				([k, v]) => !k.startsWith('__') && k !== 'id' && v !== null && v !== '' && v !== undefined
			)
			.map(([key, v]) => ({ key, value: typeof v === 'object' ? JSON.stringify(v) : String(v) }));
	}

	const detailLines = $derived(
		detail?.kind === 'invoice'
			? (lines?.rows ?? []).filter((r) => cell(r, 'invoice') === String(detail?.row.id))
			: []
	);

	const detailPostings = $derived(
		detail?.kind === 'journal'
			? (postings?.rows ?? []).filter((r) => cell(r, 'entry') === String(detail?.row.id))
			: []
	);

	/** Double-entry at a glance: the debit and credit sums the reader can
	 *  compare without trusting anyone's "balanced" claim. */
	const postingSums = $derived(
		detailPostings.reduce(
			(acc, r) => {
				const amt = Number(cell(r, 'amount')) || 0;
				if (cell(r, 'direction') === 'debit') acc.debit += amt;
				else acc.credit += amt;
				return acc;
			},
			{ debit: 0, credit: 0 }
		)
	);

	function detailTitle(): string {
		if (!detail) return '';
		if (detail.kind === 'invoice')
			return `Invoice ${cell(detail.row, 'document_number') || detail.row.id}`;
		if (detail.kind === 'journal') return `Journal ${cell(detail.row, 'slug') || detail.row.id}`;
		return cell(detail.row, 'legal_name') || String(detail.row.id);
	}
</script>

<div class="books">
	<Tabs {tabs} bind:active label="Books views" />
	{#if err}
		<StatusNote kind="error">{err}</StatusNote>
	{/if}
	<label class="owner">
		<span>book_owner</span>
		<select bind:value={bookOwner}>
			<option value="">All books</option>
			{#each owners as owner (owner)}
				<option value={owner}>{owner}</option>
			{/each}
		</select>
	</label>
	<div class="body" role="tabpanel">
		{#if active === 'queue'}
			{#if !queue}
				<StatusNote kind="loading">Loading the verify queue…</StatusNote>
			{:else if pending.length === 0}
				<StatusNote kind="empty"
					>No held invoices. Intake writes this queue; absorb books approved ones.</StatusNote
				>
			{:else}
				<table>
					<thead>
						<tr><th>Sidecar</th><th>Status</th><th></th></tr>
					</thead>
					<tbody>
						{#each pending as row (row.id)}
							{@const slug = cell(row, 'slug') || String(row.id)}
							{@const src = cell(row, 'source_path')}
							<tr>
								<td>{cell(row, 'sidecar_id') || row.id}</td>
								<td>{cell(row, 'resolution') || 'pending'}</td>
								<td>
									<button type="button" onclick={() => (openSlug = openSlug === slug ? '' : slug)}
										>{openSlug === slug ? 'Close' : 'Review'}</button
									>
								</td>
							</tr>
							{#if openSlug === slug}
								<!-- The verify surface: source NEXT TO the extraction, and the
								     verdict buttons only here — approving what you cannot see
								     is a rubber stamp. -->
								<tr class="detail">
									<td colspan="3">
										<div class="review">
											<div class="source">
												{#if sourceKind(src) === 'image'}
													<img src={vfsDownloadUrl(src)} alt="original invoice {slug}" />
												{:else if sourceKind(src) === 'pdf'}
													<object
														data={vfsDownloadUrl(src)}
														type="application/pdf"
														title="original invoice {slug}"
														><a href={vfsDownloadUrl(src)}>Open the original PDF</a></object
													>
												{:else}
													<StatusNote kind="empty"
														>No source recorded for this row (a pre-source_path sweep) — re-run the
														intake sweep to backfill, or verify against the file in the client's
														processed/ folder before deciding.</StatusNote
													>
												{/if}
											</div>
											<div class="extract">
												<table>
													<thead>
														<tr><th>Field</th><th>Extracted</th><th>Conf.</th></tr>
													</thead>
													<tbody>
														{#each fieldRows(row) as f (f.key)}
															<tr><td>{f.key}</td><td>{f.value}</td><td>{f.confidence}</td></tr>
														{/each}
													</tbody>
												</table>
												<p class="hint">
													Conf. n/a = the extractor does not report per-field confidence yet; the
													image beside is the evidence.
												</p>
												{#if queue.canWrite}
													<div class="verdict">
														<button
															type="button"
															disabled={busy === row.id}
															onclick={() => resolveRow(row, 'approved')}>Approve</button
														>
														<button
															type="button"
															disabled={busy === row.id}
															onclick={() => resolveRow(row, 'rejected')}>Reject</button
														>
													</div>
												{/if}
											</div>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			{/if}
		{:else if active === 'invoices'}
			{#if !invoices}
				<StatusNote kind="loading">Loading invoices…</StatusNote>
			{:else}
				<table>
					<thead>
						<tr
							><th>Number</th><th>Book</th><th>Seller</th><th>Buyer</th><th>Payable</th><th>Kind</th
							></tr
						>
					</thead>
					<tbody>
						<!-- The flat invoice-line table that used to sit under this one
						     ("proč jsou tam dvě tabulky") moved into the row's detail
						     modal — lines belong to AN invoice, not to the tab. -->
						{#each shownInvoices as row (row.id)}
							<tr class="click" onclick={() => (detail = { kind: 'invoice', row })}>
								<td>{cell(row, 'document_number')}</td>
								<td>{cell(row, 'book_owner')}</td>
								<td>{cell(row, 'seller__ref') || cell(row, 'seller')}</td>
								<td>{cell(row, 'buyer__ref') || cell(row, 'buyer')}</td>
								<td>{cell(row, 'payable_amount')}</td>
								<td>{cell(row, 'document_kind') || 'invoice'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{:else if active === 'journals'}
			{#if !journals}
				<StatusNote kind="loading">Loading journal entries…</StatusNote>
			{:else}
				<table>
					<thead>
						<tr><th>Slug</th><th>Description</th><th>Source</th></tr>
					</thead>
					<tbody>
						{#each shownJournals as row (row.id)}
							<tr class="click" onclick={() => (detail = { kind: 'journal', row })}>
								<td>{cell(row, 'slug') || row.id}</td>
								<td>{cell(row, 'description')}</td>
								<td>{cell(row, 'source__ref') || cell(row, 'source')}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{:else if !parties}
			<StatusNote kind="loading">Loading parties…</StatusNote>
		{:else}
			<p class="hint">
				KEAP <code>party</code> is the books fallback while Dolibarr is the CRM SoT (opt-out: these
				tables only).
				{#if crm}
					<button type="button" onclick={openCrm}>Open CRM</button>
				{/if}
			</p>
			<table>
				<thead>
					<tr><th>Name</th><th>Role</th><th>Slug</th></tr>
				</thead>
				<tbody>
					{#each shownParties as row (row.id)}
						<tr class="click" onclick={() => (detail = { kind: 'party', row })}>
							<td>{cell(row, 'legal_name')}</td>
							<td>{cell(row, 'role') || 'counterparty'}</td>
							<td><code>nos:party:{cell(row, 'slug') || row.id}</code></td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</div>

{#if detail}
	<Modal
		title={detailTitle()}
		size={detail.kind === 'party' ? 'md' : 'lg'}
		onclose={() => (detail = null)}
	>
		{#if detail.kind === 'invoice'}
			<div class="cells">
				{#each rowCells(detail.row) as c (c.key)}
					<div class="cellrow"><span class="k">{c.key}</span><span class="v">{c.value}</span></div>
				{/each}
			</div>
			{#if detailLines.length}
				<h4>Lines</h4>
				<table>
					<thead>
						<tr><th>#</th><th>Description</th><th>Net</th><th>VAT</th></tr>
					</thead>
					<tbody>
						{#each detailLines as row (row.id)}
							<tr>
								<td>{cell(row, 'line_no')}</td>
								<td>{cell(row, 'description')}</td>
								<td>{cell(row, 'net_amount')}</td>
								<td>{cell(row, 'vat_amount')}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p class="hint">No lines for this invoice.</p>
			{/if}
		{:else if detail.kind === 'journal'}
			<div class="cells">
				{#each rowCells(detail.row) as c (c.key)}
					<div class="cellrow"><span class="k">{c.key}</span><span class="v">{c.value}</span></div>
				{/each}
			</div>
			<h4>Postings</h4>
			{#if !postings}
				<p class="hint">posting table not readable at this tier.</p>
			{:else if detailPostings.length === 0}
				<p class="hint">No postings reference this entry.</p>
			{:else}
				<table>
					<thead>
						<tr><th>Account</th><th>Direction</th><th>Amount</th></tr>
					</thead>
					<tbody>
						{#each detailPostings as row (row.id)}
							<tr>
								<td>{cell(row, 'account__ref') || cell(row, 'account')}</td>
								<td>{cell(row, 'direction')}</td>
								<td>{cell(row, 'amount')}</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<p class="hint" class:err={postingSums.debit !== postingSums.credit}>
					Σ debit {postingSums.debit} · Σ credit {postingSums.credit}
					{postingSums.debit === postingSums.credit ? '— balanced' : '— NOT BALANCED'}
				</p>
			{/if}
		{:else}
			<div class="cells">
				{#each rowCells(detail.row) as c (c.key)}
					<div class="cellrow"><span class="k">{c.key}</span><span class="v">{c.value}</span></div>
				{/each}
			</div>
		{/if}
	</Modal>
{/if}

<style>
	.books {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		padding: 8px 12px;
		gap: 8px;
	}
	.body {
		flex: 1 1 auto;
		min-height: 0;
		overflow: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	th,
	td {
		text-align: left;
		padding: 6px 8px;
		border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent);
	}
	button {
		margin-right: 6px;
	}
	.hint {
		font-size: 12px;
		opacity: 0.8;
	}
	code {
		font-size: 11px;
	}
	.owner {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
	}
	.owner select {
		font: inherit;
	}
	.review {
		display: flex;
		gap: 12px;
		align-items: flex-start;
	}
	.review .source {
		flex: 1 1 55%;
		min-width: 0;
	}
	.review .source img,
	.review .source object {
		max-width: 100%;
		height: auto;
		min-height: 320px;
		border: 1px solid rgba(128, 128, 128, 0.4);
	}
	.review .extract {
		flex: 1 1 45%;
		min-width: 0;
	}
	.review .verdict {
		margin-top: 10px;
	}
	tr.detail td {
		background: rgba(128, 128, 128, 0.08);
	}
	tr.click {
		cursor: pointer;
	}
	tr.click:hover td {
		background: rgba(128, 128, 128, 0.1);
	}
	.cells {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: 6px 16px;
		margin-bottom: 10px;
	}
	.cellrow {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.cellrow .k {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.cellrow .v {
		overflow-wrap: anywhere;
	}
	h4 {
		margin: 12px 0 6px;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted, #9aa4b2);
	}
	.hint.err {
		color: #ff8080;
	}
</style>
