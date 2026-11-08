<!--
  InboxApp — Wing's inbox as a face app (row wing-inc1-inbox-app, Tier 1). The agents' open
  questions first (a blocked run waits on a person), then the unread notifications. Answers and
  "read" go through /bff/inbox; Wing decides the tier again, records the person and resolves a
  question once. What Wing said is shown in its own words: a lost race names the answer that won.
  Agent text is drawn as text, never markup.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { StatusNote, Badge } from '$lib/components/ui';
	import { answerQuestion, loadInbox, markRead, type Inbox } from '$lib/api/inbox';
	import type { AnswerOutcome } from '$lib/inbox/project';

	let inbox = $state<Inbox | null>(null);
	let failed = $state<string | null>(null);
	let busy = $state<string | null>(null);
	let draft: Record<string, string> = $state({});
	let said: Record<string, string> = $state({});

	const tone = (s: string) =>
		s === 'critical' || s === 'high' ? 'bad' : s === 'medium' ? 'warn' : 'info';

	function words(o: AnswerOutcome): string {
		switch (o.outcome) {
			case 'answered':
				return 'Answered; Wing recorded it.';
			case 'lost':
				return `NOT yours: ${o.by || 'someone'} answered first with ${o.winning}.`;
			case 'expired':
				return `Too late: the deadline passed${o.onExpiry ? ` and the agent took "${o.onExpiry}"` : ''}.`;
			default:
				return `NOT answered: ${o.why}`;
		}
	}

	async function refresh() {
		failed = null;
		try {
			inbox = await loadInbox();
		} catch (e) {
			inbox = null;
			failed = String(e);
		}
	}

	async function answer(uuid: string, text: string) {
		const a = text.trim();
		if (!a || busy) return;
		busy = uuid;
		try {
			said = { ...said, [uuid]: words(await answerQuestion(uuid, a)) };
		} catch (e) {
			said = { ...said, [uuid]: `NOT answered: ${e}` };
		} finally {
			busy = null;
		}
	}

	async function read(uuid: string) {
		if (busy) return;
		busy = uuid;
		try {
			await markRead(uuid);
			if (inbox)
				inbox = { ...inbox, notifications: inbox.notifications.filter((n) => n.uuid !== uuid) };
		} catch (e) {
			said = { ...said, [uuid]: `not marked read: ${e}` };
		} finally {
			busy = null;
		}
	}

	onMount(refresh);
</script>

<div class="inbox">
	<header>
		<strong>Inbox</strong>
		{#if inbox?.unread != null}<Badge tone="neutral" count={inbox.unread} title="unread" />{/if}
		<button class="ghost" onclick={refresh}>refresh</button>
	</header>

	{#if failed}
		<StatusNote kind="error" title="The inbox did not load">{failed}</StatusNote>
	{:else if !inbox}
		<StatusNote kind="loading">loading…</StatusNote>
	{:else}
		<section aria-label="agents' questions">
			<h3>Waiting for you ({inbox.questions.length})</h3>
			{#if inbox.questions.length === 0}
				<p class="none">No agent is waiting for an answer.</p>
			{/if}
			{#each inbox.questions as q (q.uuid)}
				<article>
					<p class="who">
						<Badge tone={tone(q.severity)}>{q.severity}</Badge>
						{q.agent} asks ({q.kind}){#if q.expires}<span>
								· until {q.expires}{q.onExpiry ? `, then "${q.onExpiry}"` : ''}</span
							>{/if}
					</p>
					<p class="prompt">{q.prompt}</p>
					{#if said[q.uuid]}
						<p class="said">{said[q.uuid]}</p>
					{:else if q.options}
						<div class="options">
							{#each q.options as o (o)}
								<button disabled={busy !== null} onclick={() => answer(q.uuid, o)}>{o}</button>
							{/each}
						</div>
					{:else}
						<form
							onsubmit={(e) => {
								e.preventDefault();
								answer(q.uuid, draft[q.uuid] ?? '');
							}}
						>
							<label for={`inbox-answer-${q.uuid}`}>Answer</label>
							<input id={`inbox-answer-${q.uuid}`} bind:value={draft[q.uuid]} autocomplete="off" />
							<button type="submit" disabled={busy !== null || !(draft[q.uuid] ?? '').trim()}
								>send</button
							>
						</form>
					{/if}
				</article>
			{/each}
		</section>

		<section aria-label="unread notifications">
			<h3>Unread ({inbox.notifications.length})</h3>
			{#if inbox.notifications.length === 0}
				<p class="none">Nothing unread.</p>
			{/if}
			{#each inbox.notifications as n (n.uuid)}
				<article>
					<p class="who">
						<Badge tone={tone(n.severity)}>{n.severity}</Badge>
						{n.title}
					</p>
					<p class="meta">{n.from}{n.from && n.created ? ' · ' : ''}{n.created}</p>
					{#if n.body}<details>
							<summary>detail</summary>
							<pre>{n.body}</pre>
						</details>{/if}
					{#if said[n.uuid]}<p class="said">{said[n.uuid]}</p>{/if}
					<button class="ghost" disabled={busy !== null} onclick={() => read(n.uuid)}
						>mark read</button
					>
				</article>
			{/each}
		</section>
	{/if}
</div>

<style>
	.inbox {
		display: grid;
		gap: 12px;
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
	h3 {
		margin: 4px 0;
		font-size: 0.95em;
	}
	article {
		display: grid;
		gap: 4px;
		padding: 8px 0;
		border-bottom: 1px solid var(--line, currentColor);
	}
	.who,
	.prompt,
	.meta,
	.said,
	.none {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.meta {
		font-size: 0.85em;
		opacity: 0.7;
	}
	pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		margin: 4px 0;
	}
	.options,
	form {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		align-items: center;
	}
	label {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	input {
		flex: 1;
		min-width: 0;
	}
</style>
