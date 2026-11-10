<!--
  InboxApp — Wing's inbox as a face app (row wing-inc1-inbox-app, Tier 1). The agents' open
  questions first (a blocked run waits on a person), then the unread notifications. Answers and
  "read" go through /bff/inbox; Wing decides the tier again, records the person and resolves a
  question once. What Wing said is shown in its own words: a lost race names the answer that won.
  Agent text is drawn as text, never markup.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { StatusNote, Badge, severityTone as tone } from '$lib/components/ui';
	import { answerQuestion, loadInbox, markRead, type Inbox } from '$lib/api/inbox';
	import type { AnswerOutcome } from '$lib/inbox/project';

	let inbox = $state<Inbox | null>(null);
	let failed = $state<string | null>(null);
	let busy = $state<string | null>(null);
	let draft: Record<string, string> = $state({});
	let said: Record<string, { text: string; ok: boolean }> = $state({});

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
			const o = await answerQuestion(uuid, a);
			said = { ...said, [uuid]: { text: words(o), ok: o.outcome === 'answered' } };
		} catch (e) {
			said = { ...said, [uuid]: { text: `NOT answered: ${e}`, ok: false } };
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
			said = { ...said, [uuid]: { text: `not marked read: ${e}`, ok: false } };
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
				<StatusNote kind="empty" title="No agent is waiting for an answer." />
			{/if}
			{#each inbox.questions as q (q.uuid)}
				<article class:done={!!said[q.uuid]?.ok}>
					<p class="who">
						<Badge tone={tone(q.severity)}>{q.severity}</Badge>
						{q.agent} asks ({q.kind}){#if q.expires}<span>
								· until {q.expires}{q.onExpiry ? `, then "${q.onExpiry}"` : ''}</span
							>{/if}
					</p>
					<p class="prompt">{q.prompt}</p>
					{#if said[q.uuid]}
						<p class="said" class:ok={said[q.uuid].ok} role="status">{said[q.uuid].text}</p>
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
				<StatusNote kind="empty" title="Nothing unread." />
			{/if}
			{#each inbox.notifications as n (n.uuid)}
				<article class="unread">
					<p class="who">
						<Badge tone={tone(n.severity)}>{n.severity}</Badge>
						{n.title}
					</p>
					<p class="meta">{n.from}{n.from && n.created ? ' · ' : ''}{n.created}</p>
					{#if n.body}<details>
							<summary>detail</summary>
							<pre>{n.body}</pre>
						</details>{/if}
					{#if said[n.uuid]}<p class="said" role="status">{said[n.uuid].text}</p>{/if}
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
		align-content: start;
		gap: 14px;
		padding: 12px;
		overflow: auto;
		height: 100%;
		box-sizing: border-box;
		container-type: inline-size;
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
		gap: 6px;
		padding: 8px 10px;
		border: 1px solid var(--glass-brd);
		border-left: 3px solid var(--accent);
		border-radius: 8px;
		background: var(--glass);
	}
	article.unread {
		border-left-color: var(--info);
	}
	article.done {
		border-left-color: var(--glass-brd);
		opacity: 0.7;
	}
	.who {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
	}
	.who span,
	.meta {
		font-size: 0.85em;
		color: var(--muted);
	}
	.who,
	.prompt,
	.meta,
	.said {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.prompt {
		white-space: pre-wrap;
	}
	.said {
		color: var(--bad);
	}
	.said.ok {
		color: var(--ok);
	}
	summary {
		cursor: pointer;
		color: var(--muted);
		font-size: 0.85em;
	}
	pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		margin: 4px 0 0;
		font-size: 0.85em;
	}
	article > button {
		justify-self: start;
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
	@container (max-width: 360px) {
		.inbox {
			padding: 8px;
		}
		form {
			flex-direction: column;
			align-items: stretch;
		}
		.options button {
			flex: 1 1 100%;
		}
	}
</style>
