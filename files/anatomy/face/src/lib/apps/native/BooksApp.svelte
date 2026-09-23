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
	import { Tabs, StatusNote, type TabSpec } from '$lib/components/ui';
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
	let err = $state('');
	let busy = $state('');
	let crm = $state<HubApp | null>(null);
	let bookOwner = $state('');

	onMount(async () => {
		try {
			const [q, i, j, p, ln, hub] = await Promise.all([
				loadTable('pending-invoice-verify'),
				loadTable('invoice'),
				loadTable('journal-entry'),
				loadTable('party'),
				loadTable('invoice-line'),
				hubApps().catch(() => [] as HubApp[])
			]);
			queue = q;
			invoices = i;
			journals = j;
			parties = p;
			lines = ln;
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
				confidence: d.confidence === undefined ? '' : String(d.confidence)
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
			const next: Record<string, unknown> = {
				...row,
				resolution,
				resolved_at: new Date().toISOString().slice(0, 10)
			};
			delete next.id;
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

	const shownLines = $derived(
		(lines?.rows ?? []).filter((r) => invoiceSlugs.has(cell(r, 'invoice')))
	);

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
						{#each shownInvoices as row (row.id)}
							<tr>
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
				{#if shownLines.length}
					<table>
						<thead>
							<tr><th>Invoice</th><th>#</th><th>Description</th><th>Net</th><th>VAT</th></tr>
						</thead>
						<tbody>
							{#each shownLines as row (row.id)}
								<tr>
									<td>{cell(row, 'invoice')}</td>
									<td>{cell(row, 'line_no')}</td>
									<td>{cell(row, 'description')}</td>
									<td>{cell(row, 'net_amount')}</td>
									<td>{cell(row, 'vat_amount')}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
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
							<tr>
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
						<tr>
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
</style>
