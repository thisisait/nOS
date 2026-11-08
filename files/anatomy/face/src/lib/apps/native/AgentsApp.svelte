<!--
  AgentsApp — Wing's agents page as a face app (row wing-inc2-agents-timeline, Tier 1): the roster,
  one agent's sessions, and stopping a running one. Wing decides every verb
  again; a stop answers with what Wing said (202 cancelled, 409 not running, 404 not yours).
  Starting a run stays where people already start one (Iris, the CLI); no vault picker
  (operator 2026-11-08: agents declare their vault).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { StatusNote, Badge } from '$lib/components/ui';
	import { cancelSession, loadRoster, loadSessions } from '$lib/api/agents';
	import type { RosterAgent } from '$lib/agents/roster';
	import type { SessionView } from '$lib/agents/sessions';

	let roster = $state<RosterAgent[] | null>(null);
	let failed = $state<string | null>(null);
	let picked = $state<string | null>(null);
	let sessions = $state<SessionView[] | null>(null);
	let sessionsFailed = $state<string | null>(null);
	let said: Record<string, string> = $state({});
	let busy = $state<string | null>(null);

	const tone = (s: string) =>
		s === 'running'
			? 'info'
			: s === 'failed' || s === 'error'
				? 'bad'
				: s === 'completed'
					? 'ok'
					: 'neutral';

	async function refresh() {
		failed = null;
		try {
			roster = await loadRoster();
		} catch (e) {
			roster = null;
			failed = String(e);
		}
	}

	async function pick(name: string) {
		picked = name;
		sessions = null;
		sessionsFailed = null;
		try {
			sessions = await loadSessions(name);
		} catch (e) {
			sessionsFailed = String(e);
		}
	}

	async function stop(uuid: string) {
		if (busy) return;
		busy = uuid;
		try {
			const r = await cancelSession(uuid);
			said = { ...said, [uuid]: `stopped: ${r.status}; the run ends before its next model call` };
			if (picked) await pick(picked);
		} catch (e) {
			said = { ...said, [uuid]: `NOT stopped: ${e}` };
		} finally {
			busy = null;
		}
	}

	onMount(refresh);
</script>

<div class="agents">
	<aside aria-label="agents">
		<header>
			<strong>Agents</strong>
			<button class="ghost" onclick={refresh}>refresh</button>
		</header>
		{#if failed}
			<StatusNote kind="error" title="The roster did not load">{failed}</StatusNote>
		{:else if !roster}
			<StatusNote kind="loading">loading…</StatusNote>
		{:else if roster.length === 0}
			<StatusNote kind="empty" title="No agent is defined" />
		{:else}
			<ul>
				{#each roster as a (a.name)}
					<li>
						<button class:on={picked === a.name} onclick={() => pick(a.name)}>
							<span class="name">{a.name}</span>
							{#if a.error}<Badge tone="bad">does not load</Badge>{:else if a.gated}<Badge
									tone="info">gated</Badge
								>{/if}
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</aside>

	<section aria-label="sessions">
		{#if !picked}
			<p class="none">Pick an agent to see its runs.</p>
		{:else}
			{@const agent = roster?.find((a) => a.name === picked)}
			<h3>{picked}</h3>
			{#if agent?.error}<p class="error">{agent.error}</p>{:else if agent?.description}<p
					class="desc"
				>
					{agent.description}
				</p>{/if}
			{#if sessionsFailed}
				<StatusNote kind="error" title="Its runs did not load">{sessionsFailed}</StatusNote>
			{:else if !sessions}
				<StatusNote kind="loading">loading…</StatusNote>
			{:else if sessions.length === 0}
				<StatusNote kind="empty" title="No run recorded" />
			{:else}
				<table>
					<thead>
						<tr><th>status</th><th>started</th><th>ended</th><th></th></tr>
					</thead>
					<tbody>
						{#each sessions as s (s.uuid)}
							<tr>
								<td><Badge tone={tone(s.status)}>{s.status}</Badge></td>
								<td>{s.startedAt ?? '—'}</td>
								<td>{s.endedAt ?? ''}{s.stopReason ? ` (${s.stopReason})` : ''}</td>
								<td>
									{#if said[s.uuid]}<span class="said">{said[s.uuid]}</span>
									{:else if s.status === 'running'}<button
											disabled={busy !== null}
											onclick={() => stop(s.uuid)}>stop</button
										>{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{/if}
	</section>
</div>

<style>
	.agents {
		display: grid;
		grid-template-columns: minmax(160px, 220px) 1fr;
		height: 100%;
		min-height: 0;
	}
	aside,
	section {
		overflow: auto;
		padding: 10px;
		min-width: 0;
	}
	aside {
		border-right: 1px solid var(--line, currentColor);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	ul {
		list-style: none;
		margin: 8px 0 0;
		padding: 0;
		display: grid;
		gap: 2px;
	}
	li button {
		width: 100%;
		display: flex;
		gap: 6px;
		align-items: center;
		justify-content: space-between;
		text-align: left;
	}
	li button.on {
		font-weight: 600;
	}
	.name,
	.desc,
	.error,
	.said {
		overflow-wrap: anywhere;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}
	th,
	td {
		text-align: left;
		padding: 4px 6px;
		border-bottom: 1px solid var(--line, currentColor);
	}
	.none {
		opacity: 0.7;
	}
</style>
