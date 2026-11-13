<!--
  AwaitingApp — "Awaiting you" (row face-app-awaiting, Tier 1): what cannot move without the operator,
  read-only. Agent questions and urgent unread notifications come from Wing, the person's open Iris cards
  from the thalamus (a read hello), all through /bff/awaiting; each
  row hands off to the Inbox app, the one place that answers (Q15). The sources the face cannot reach are
  named, so an empty list never reads as "nothing waits" when part of the estate was not asked.
  Agent text is drawn as text, never markup.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { StatusNote, Badge } from '$lib/components/ui';
	import { loadAwaiting } from '$lib/api/awaiting';
	import type { Awaiting } from '$lib/awaiting/project';
	import { openApp } from './registry';

	let awaiting = $state<Awaiting | null>(null);
	let failed = $state<string | null>(null);

	async function refresh() {
		failed = null;
		try {
			awaiting = await loadAwaiting();
		} catch (e) {
			awaiting = null;
			failed = String(e);
		}
	}

	const groups = $derived(
		awaiting
			? [
					{ kind: 'question', title: 'Agents waiting for an answer' },
					{ kind: 'alert', title: 'Critical or high, unread' },
					{ kind: 'approval', title: 'Iris cards waiting for your approval' },
					{ kind: 'proposal', title: 'Loop proposals not yet landed' }
				].map((g) => ({ ...g, rows: awaiting!.items.filter((i) => i.kind === g.kind) }))
			: []
	);

	onMount(refresh);
</script>

<div class="awaiting">
	<header>
		<strong>Awaiting you</strong>
		{#if awaiting}<Badge tone="neutral" count={awaiting.items.length} title="waiting" />{/if}
		<button class="ghost" onclick={refresh}>refresh</button>
	</header>

	{#if failed}
		<StatusNote kind="error" title="What awaits you did not load">{failed}</StatusNote>
	{:else if !awaiting}
		<StatusNote kind="loading">loading…</StatusNote>
	{:else}
		{#each groups as g (g.kind)}
			<section aria-label={g.title}>
				<h3>{g.title} ({g.rows.length})</h3>
				{#if g.rows.length === 0}
					<StatusNote kind="empty" title="Nothing of this kind waits." />
				{/if}
				{#each g.rows as r (r.id)}
					<article>
						<p>{r.title}</p>
						<p class="meta">
							{r.since}
							{#if r.kind === 'approval'}
								<button class="ghost" onclick={() => openApp('iris')}>open in Iris</button>
							{:else if r.kind === 'proposal'}
								<button class="ghost" onclick={() => openApp('anatomy')}>open in Anatomy</button>
							{:else}
								<button class="ghost" onclick={() => openApp('inbox')}>open in Inbox</button>
							{/if}
						</p>
					</article>
				{/each}
			</section>
		{/each}
		{#if awaiting.unknown.length}
			<StatusNote kind="error" title="Asked, no answer">{awaiting.unknown.join('; ')}</StatusNote>
		{/if}
		<StatusNote kind="empty" title="Not asked from here">
			The face cannot reach {awaiting.unreachable.join('; ')}.
			<code>tools/awaiting-operator.py</code> lists them on the host.
		</StatusNote>
	{/if}
</div>

<style>
	.awaiting {
		display: grid;
		align-content: start;
		gap: 14px;
		padding: 12px;
		overflow: auto;
		height: 100%;
		box-sizing: border-box;
	}
	header {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	header button {
		margin-left: auto;
	}
	section {
		display: grid;
		gap: 6px;
	}
	h3 {
		margin: 0;
		font-size: 0.8em;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--muted);
	}
	article {
		display: grid;
		gap: 4px;
		padding: 8px 10px;
		border: 1px solid var(--glass-brd);
		border-left: 3px solid var(--accent);
		border-radius: 8px;
		background: var(--glass);
	}
	article p {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.meta {
		display: flex;
		gap: 8px;
		align-items: center;
		font-size: 0.85em;
		color: var(--muted);
	}
	.meta button {
		margin-left: auto;
	}
</style>
