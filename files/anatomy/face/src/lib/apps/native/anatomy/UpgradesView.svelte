<!--
  Upgrades view — what Wing's /upgrades page shows, read-only.

  The matrix (installed, next step, latest, the security floor), the planned queue and the last applied
  upgrades, through GET /bff/upgrades. There is no button here on purpose: queue, plan, promote and apply
  stay in Wing, and the one link goes there. An unwired token, a Wing that did not answer and a genuinely
  empty catalog are three different notes, never one empty table.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { loadUpgrades, type UpgradesResponse } from '$lib/api/pulse';
	import { StatusNote, Badge, Panel } from '$lib/components/ui';
	import type { Tone } from '$lib/components/ui';

	let data = $state<UpgradesResponse | null>(null);
	let err = $state('');
	let loading = $state(true);

	const POLL_MS = 120_000;
	let timer: ReturnType<typeof setInterval> | undefined;

	async function refresh() {
		try {
			data = await loadUpgrades();
			err = '';
		} catch (e) {
			err = e instanceof Error ? e.message : 'could not reach the BFF';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void refresh();
		timer = setInterval(() => void refresh(), POLL_MS);
	});
	onDestroy(() => clearInterval(timer));

	/** Wing's own class words (current / minor / breaking / critical / unknown) on the shell's tones. */
	function tone(cls: string): Tone {
		if (cls === 'current') return 'ok';
		if (cls === 'critical' || cls === 'breaking') return 'bad';
		if (cls === 'minor') return 'warn';
		return 'neutral';
	}

	const services = $derived(data?.services ?? []);
	const planned = $derived(data?.planned ?? []);
	const history = $derived(data?.history ?? []);
</script>

<div class="upgrades">
	{#if loading}
		<StatusNote kind="loading">Reading Wing’s upgrade matrix…</StatusNote>
	{:else if err}
		<StatusNote kind="error" title="The face BFF did not answer">{err}</StatusNote>
	{:else if data && !data.configured}
		<StatusNote kind="unwired" title="Wing is not wired to this face">{data.note}</StatusNote>
	{:else if data}
		<p class="verbs">
			Read-only here. To queue, plan or promote an upgrade, use
			{#if data.wingUrl}
				<a href="{data.wingUrl}/upgrades" target="_blank" rel="noopener noreferrer"
					>Wing → Upgrades</a
				>.
			{:else}
				Wing’s Upgrades page.
			{/if}
		</p>
		{#if data.error}
			<StatusNote kind="error" title="Wing did not answer">
				{data.error}. Nothing below was read.
			</StatusNote>
		{:else}
			<Panel title="Services · {services.length}">
				{#if services.length === 0}
					<StatusNote kind="empty" title="No service has an upgrade recipe" />
				{:else}
					<table>
						<thead>
							<tr>
								<th>Service</th>
								<th>Installed</th>
								<th>Next</th>
								<th>Latest</th>
								<th>Severity</th>
								<th>Security</th>
								<th>Next recipe</th>
							</tr>
						</thead>
						<tbody>
							{#each services as s, i (i)}
								<tr>
									<td><code>{s.service}</code></td>
									<td><Badge tone={tone(s.installedClass)}>{s.installed ?? 'unknown'}</Badge></td>
									<td><Badge tone={tone(s.stableClass)}>{s.stable ?? '—'}</Badge></td>
									<td><Badge tone={tone(s.latestClass)}>{s.latest ?? '—'}</Badge></td>
									<td>{s.severity}</td>
									<td>
										{#if s.security === null}
											—
										{:else if s.security.unavailable}
											<Badge tone="warn">unknown</Badge>
										{:else}
											<Badge tone={s.security.pending ? 'bad' : 'ok'}>
												{s.security.pending} pending{s.security.floor
													? ` · floor ${s.security.floor}`
													: ''}
											</Badge>
										{/if}
									</td>
									<td>
										{#if s.aheadOfCatalog}
											<span class="muted">recipes are behind the installed version</span>
										{:else}
											<code>{s.nextRecipeId || '—'}</code>
											<span class="muted">
												of {s.recipeCount}{s.coexistenceSupported ? ' · coexistence' : ''}
											</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</Panel>

			<Panel title="Planned · {planned.length}">
				{#if planned.length === 0}
					<StatusNote kind="empty" title="Nothing is queued" />
				{:else}
					<table>
						<thead>
							<tr><th>Service</th><th>Recipe</th><th>Target</th><th>Status</th><th>Planned</th></tr>
						</thead>
						<tbody>
							{#each planned as p, i (i)}
								<tr>
									<td><code>{p.service}</code></td>
									<td><code>{p.recipeId}</code></td>
									<td>{p.targetVersion ?? '—'}</td>
									<td>{p.status}</td>
									<td>{p.plannedAt ?? '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</Panel>

			<Panel title="Applied · last {history.length}">
				{#if history.length === 0}
					<StatusNote kind="empty" title="No upgrade has been applied" />
				{:else}
					<table>
						<thead>
							<tr
								><th>Service</th><th>Recipe</th><th>From</th><th>To</th><th>Result</th><th
									>Applied</th
								></tr
							>
						</thead>
						<tbody>
							{#each history as h, i (i)}
								<tr>
									<td><code>{h.service}</code></td>
									<td><code>{h.recipeId}</code></td>
									<td>{h.fromVersion ?? '—'}</td>
									<td>{h.toVersion ?? '—'}</td>
									<td>
										<Badge tone={h.rolledBack ? 'warn' : h.success ? 'ok' : 'bad'}>
											{h.rolledBack ? 'rolled back' : h.success ? 'applied' : 'failed'}
										</Badge>
									</td>
									<td>{h.appliedAt ?? '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</Panel>
		{/if}
	{/if}
</div>

<style>
	.upgrades {
		font-size: 13px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.verbs {
		margin: 0;
		color: var(--muted);
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th,
	td {
		text-align: left;
		padding: 4px 8px;
		border-bottom: 1px solid var(--border, rgba(127, 127, 127, 0.2));
		vertical-align: top;
	}
	th {
		font-weight: 600;
		color: var(--muted);
	}
	.muted {
		color: var(--muted);
	}
</style>
