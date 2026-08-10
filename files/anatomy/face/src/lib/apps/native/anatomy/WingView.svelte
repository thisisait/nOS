<!--
  Wing view — the audit spine and the notification inbox.

  It does NOT rebuild Wing UI. Upgrades, agents and migrations live there and
  work; a second copy is a second thing to keep correct. What this adds is the
  THREAD: an `actor_action_id` shared by a Pulse run and every event it
  produced. Open a run in the Pulse view, follow it here, and the two lists
  narrow to that one action.

  The inbox column shows delivery as CLAIMED, with the error beside the stamp.
  A dispatch time is written by the sender; an error written next to it means
  the stamp is not a delivery. Showing "sent" alone would be the estate's
  oldest defect rendered in CSS.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { loadWing, type WingResponse } from '$lib/api/pulse';
	import type { WingEventView, WingNotificationView } from '$lib/anatomy/wing';
	import { StatusNote, Badge, StateDot, Panel, severityTone } from '$lib/components/ui';

	interface Props {
		/** actor_action_id to narrow to, set by the shell when the operator
		 *  follows a Pulse run. Empty = the unfiltered recent view. */
		thread?: string;
		onclearthread?: () => void;
	}
	let { thread = '', onclearthread }: Props = $props();

	let data = $state<WingResponse | null>(null);
	let err = $state('');
	let loading = $state(true);

	const POLL_MS = 60_000;
	let timer: ReturnType<typeof setInterval> | undefined;

	async function refresh() {
		try {
			data = await loadWing(thread);
			err = '';
		} catch (e) {
			err = e instanceof Error ? e.message : 'could not reach the BFF';
		} finally {
			loading = false;
		}
	}

	// Re-fetch when the shell changes the thread, not only on mount.
	$effect(() => {
		void thread;
		loading = true;
		void refresh();
	});

	onMount(() => {
		timer = setInterval(() => void refresh(), POLL_MS);
	});
	onDestroy(() => clearInterval(timer));

	const events = $derived((data?.events ?? []) as WingEventView[]);
	const notifications = $derived((data?.notifications ?? []) as WingNotificationView[]);

	function short(ts: string): string {
		return ts.replace('T', ' ').replace('Z', '').slice(0, 19);
	}
</script>

<div class="wing">
	{#if loading}
		<StatusNote kind="loading">Reading the audit spine…</StatusNote>
	{:else if err}
		<StatusNote kind="error" title="The face BFF did not answer">{err}</StatusNote>
	{:else if data && data.configured === false}
		<StatusNote kind="unwired" title="Not wired up">{data.note}</StatusNote>
	{:else if data?.error}
		<StatusNote kind="error" title="Wing did not answer">
			{data.error} — nothing below was checked.
		</StatusNote>
	{:else}
		{#if thread}
			<div class="thread">
				<Badge tone="info">thread</Badge>
				<code>{thread}</code>
				<button onclick={() => onclearthread?.()}>show everything</button>
			</div>
		{/if}

		<div class="cols">
			<Panel title="Events">
				{#snippet aside()}
					<span class="of">{events.length} shown of {data?.eventsTotal ?? 0} recorded</span>
				{/snippet}
				{#if events.length === 0}
					<StatusNote kind="empty" title="No events match">
						{thread
							? 'Nothing was recorded under this thread. A run that produced no events is a real answer — it means nothing reported.'
							: 'Wing holds no events at all.'}
					</StatusNote>
				{:else}
					<ul class="ev">
						{#each events as e (e.id)}
							<li>
								<span class="ts">{short(e.ts)}</span>
								<span class="type">{e.type}</span>
								{#if e.actorId}<Badge tone="neutral" outline>{e.actorId}</Badge>{/if}
								{#if !e.chained}
									<!-- The audit chain is the evidence a row was not edited.
									     A row outside it is not proof of anything. -->
									<Badge tone="warn" outline title="no audit-chain hash on this row">
										unchained
									</Badge>
								{/if}
								{#if e.task}<span class="task">{e.task}</span>{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</Panel>

			<Panel title="Inbox">
				{#snippet aside()}
					{#if (data?.contestedDeliveries ?? 0) > 0}
						<Badge tone="bad" count={data?.contestedDeliveries}>
							&nbsp;claimed sent with an error
						</Badge>
					{/if}
				{/snippet}
				{#if notifications.length === 0}
					<StatusNote kind="empty" title="No notifications">
						Nothing has been raised{thread ? ' under this thread' : ''}.
					</StatusNote>
				{:else}
					<ul class="nt">
						{#each notifications as n (n.id)}
							<li class:unread={!n.read}>
								<div class="head">
									<StateDot tone={severityTone(n.severity)} label={n.severity || 'unknown'} />
									<span class="title">{n.title}</span>
									{#if n.originPlugin}<Badge tone="neutral" outline>{n.originPlugin}</Badge>{/if}
								</div>
								{#if n.body}<p class="body">{n.body}</p>{/if}
								<div class="ch">
									{#each n.channels as c (c)}<Badge tone="neutral">{c}</Badge>{/each}
									{#if n.ntfyAt}
										<Badge tone={n.ntfyError ? 'bad' : 'ok'}>
											ntfy {n.ntfyError ? 'stamped, errored' : 'sent'}
										</Badge>
									{/if}
									{#if n.mailAt}
										<Badge tone={n.mailError ? 'bad' : 'ok'}>
											mail {n.mailError ? 'stamped, errored' : 'sent'}
										</Badge>
									{/if}
								</div>
								{#if n.ntfyError || n.mailError}
									<StatusNote kind="error" block={false}>
										{n.ntfyError || n.mailError}
									</StatusNote>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</Panel>
		</div>
	{/if}
</div>

<style>
	.wing {
		font-size: 13px;
	}
	.thread {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
		font-size: 11px;
	}
	.thread code {
		font-family: ui-monospace, monospace;
		color: var(--fg, #e8ecf3);
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.thread button {
		margin-left: auto;
		background: none;
		border: 1px solid var(--glass-brd, rgba(255, 255, 255, 0.12));
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.cols {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
		align-items: start;
	}
	@media (max-width: 820px) {
		.cols {
			grid-template-columns: 1fr;
		}
	}
	/* h3 removed 2026-08-05 — the section heading treatment is <Panel>'s now,
	   in one place instead of four. */
	.of {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		opacity: 0.8;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.ev li {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 6px;
		border-radius: 6px;
		font-size: 11px;
		overflow: hidden;
	}
	.ev li:nth-child(odd) {
		background: rgba(255, 255, 255, 0.03);
	}
	.ts {
		font-family: ui-monospace, monospace;
		color: var(--muted, #9aa4b2);
		white-space: nowrap;
	}
	.type {
		font-weight: 600;
		white-space: nowrap;
	}
	.task {
		color: var(--muted, #9aa4b2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.nt li {
		padding: 8px;
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.03);
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.nt li.unread {
		background: rgba(255, 255, 255, 0.07);
	}
	.nt .head {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.nt .title {
		font-weight: 600;
		font-size: 12px;
	}
	.nt .body {
		margin: 0;
		font-size: 11px;
		line-height: 1.5;
		color: var(--muted, #9aa4b2);
	}
	.ch {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
</style>
