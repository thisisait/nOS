<!--
  Books — consulting-firm accounting in face (queue, invoices, parties).

  Tables stay SoT. This is a projection: approve/reject writes pending-invoice-verify
  through the same BFF upsert TablesApp uses (HMAC table.upsert). Espo relationships
  are a join key in Account.description (`nos:party:<slug>`), opened as a hub frame.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { hubApps } from '$lib/api/hub';
	import { ApiError } from '$lib/api/client';
	import type { DataTable, DataTableRow, HubApp } from '$lib/contracts';
	import { Tabs, StatusNote, type TabSpec } from '$lib/components/ui';
	import { openWindow, focusApp } from '$lib/stores/desktop';

	const tabs: TabSpec[] = [
		{ key: 'queue', label: 'Queue' },
		{ key: 'invoices', label: 'Invoices' },
		{ key: 'parties', label: 'Parties' }
	];
	let active = $state('queue');
	let queue = $state<DataTable | null>(null);
	let invoices = $state<DataTable | null>(null);
	let parties = $state<DataTable | null>(null);
	let err = $state('');
	let busy = $state('');
	let espo = $state<HubApp | null>(null);
	let bookOwner = $state('');

	onMount(async () => {
		try {
			const [q, i, p, hub] = await Promise.all([
				loadTable('pending-invoice-verify'),
				loadTable('invoice'),
				loadTable('party'),
				hubApps().catch(() => [] as HubApp[])
			]);
			queue = q;
			invoices = i;
			parties = p;
			espo = hub.find((a) => a.slug === 'espocrm') ?? null;
		} catch (e) {
			err = e instanceof Error ? e.message : 'could not load books';
		}
	});

	function cell(row: DataTableRow, key: string): string {
		const v = row[key];
		if (v === null || v === undefined) return '';
		return String(v);
	}

	async function resolveRow(row: DataTableRow, resolution: 'approved' | 'rejected') {
		if (!queue?.canWrite) return;
		busy = String(row.id);
		err = '';
		try {
			const next: Record<string, unknown> = { ...row, resolution, resolved_at: new Date().toISOString().slice(0, 10) };
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

	function openEspo() {
		if (!espo) return;
		if (!focusApp(espo.slug)) {
			openWindow({ app: espo.slug, title: espo.title, w: 720, h: 480, url: espo.url, embed: espo.embed });
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
				<StatusNote kind="empty">No held invoices. Intake writes this queue; absorb books approved ones.</StatusNote>
			{:else}
				<table>
					<thead>
						<tr><th>Sidecar</th><th>Status</th><th></th></tr>
					</thead>
					<tbody>
						{#each pending as row (row.id)}
							<tr>
								<td>{cell(row, 'sidecar_id') || row.id}</td>
								<td>{cell(row, 'resolution') || 'pending'}</td>
								<td>
									{#if queue.canWrite}
										<button type="button" disabled={busy === row.id} onclick={() => resolveRow(row, 'approved')}>Approve</button>
										<button type="button" disabled={busy === row.id} onclick={() => resolveRow(row, 'rejected')}>Reject</button>
									{/if}
								</td>
							</tr>
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
						<tr><th>Number</th><th>Book</th><th>Seller</th><th>Buyer</th><th>Payable</th><th>Kind</th></tr>
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
			{/if}
		{:else}
			{#if !parties}
				<StatusNote kind="loading">Loading parties…</StatusNote>
			{:else}
				<p class="hint">
					Espo Account.description carries <code>nos:party:&lt;slug&gt;</code>
					after <code>tools/espo-party-sync.py --write</code>.
					{#if espo}
						<button type="button" onclick={openEspo}>Open EspoCRM</button>
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
	th, td {
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
</style>
