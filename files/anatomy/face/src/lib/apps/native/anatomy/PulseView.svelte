<!--
  Pulse view — every scheduled job, and an honest account of the ones that
  are not running.

  THE FIRST SCREENFUL IS THE POINT. Jobs are sorted worst-first (failing, never
  ran, overdue, running, ok) and the summary bar leads with the counts that
  should be zero. An operator who opens this and scrolls nothing has still seen
  every problem.

  Absence never renders as calm:
    - `configured: false` says the token is not wired, and says nothing else.
    - an upstream error says Wing did not answer.
    - a job that has never run says NEVER RAN, in the same weight as a failure.

  All values render escaped ({expr}); no {@html} anywhere.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { loadPulse, loadRuns, type PulseResponse, type PulseRunRow } from '$lib/api/pulse';
	import type { PulseJobView, PulseState } from '$lib/anatomy/pulse';

	let data = $state<PulseResponse | null>(null);
	let err = $state('');
	let loading = $state(true);
	let selected = $state<string | null>(null);
	let runs = $state<PulseRunRow[]>([]);
	let runsErr = $state('');
	let loadingRuns = $state(false);

	// 60s. The data changes on a cron, and the fastest job here fires once a
	// minute — polling faster would burn requests to re-render the same rows.
	const POLL_MS = 60_000;
	let timer: ReturnType<typeof setInterval> | undefined;

	async function refresh() {
		try {
			data = await loadPulse();
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

	async function select(id: string) {
		if (selected === id) {
			selected = null;
			return;
		}
		selected = id;
		loadingRuns = true;
		runsErr = '';
		runs = [];
		try {
			const r = await loadRuns(id);
			runs = r.runs;
			runsErr = r.error ?? '';
		} catch (e) {
			runsErr = e instanceof Error ? e.message : 'could not load runs';
		} finally {
			loadingRuns = false;
		}
	}

	const STATE_LABEL: Record<PulseState, string> = {
		failing: 'failing',
		never: 'never ran',
		overdue: 'overdue',
		running: 'running',
		ok: 'ok'
	};

	/** "3d 4h", "22m" — a duration a human reads at a glance. */
	function ago(iso: string | null): string {
		if (!iso) return '—';
		const t = Date.parse(iso);
		if (Number.isNaN(t)) return '—';
		return dur(Math.max(0, Math.floor((Date.now() - t) / 1000)));
	}

	function dur(s: number): string {
		if (s < 60) return `${s}s`;
		if (s < 3600) return `${Math.floor(s / 60)}m`;
		if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
		return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
	}

	function ms(v: number | null): string {
		return v === null ? '—' : v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`;
	}

	const jobs = $derived((data?.jobs ?? []) as PulseJobView[]);
	const counts = $derived(data?.counts);
</script>

<div class="pulse">
	{#if loading}
		<p class="note">Reading the job catalog…</p>
	{:else if err}
		<p class="bad">The face BFF did not answer: {err}</p>
	{:else if data && data.configured === false}
		<!-- A deployment fact, stated as one. Not an empty list. -->
		<p class="bad">Not wired up: {data.note}</p>
	{:else if data?.error}
		<p class="bad">Wing did not answer: {data.error} — nothing below was checked.</p>
	{:else}
		<header class="bar">
			<span class="c total">{counts?.total ?? 0} jobs</span>
			{#if counts && counts.failing > 0}<span class="c failing">{counts.failing} failing</span>{/if}
			{#if counts && counts.never > 0}<span class="c never">{counts.never} never ran</span>{/if}
			{#if counts && counts.overdue > 0}<span class="c overdue">{counts.overdue} overdue</span>{/if}
			{#if counts && counts.paused > 0}<span class="c paused">{counts.paused} paused</span>{/if}
			{#if counts && counts.ok > 0}<span class="c ok">{counts.ok} ok</span>{/if}
			<span class="win">last {data?.windowHours ?? 24}h</span>
		</header>

		{#if jobs.length === 0}
			<p class="note">
				Wing answered and reported no registered jobs at all. That is a real answer, not a
				loading state — if you expect jobs here, the plugin loader has not run.
			</p>
		{/if}

		<ul class="rows">
			{#each jobs as j (j.id)}
				<li class="row" class:open={selected === j.id}>
					<button class="head" onclick={() => void select(j.id)}>
						<span class="dot {j.state}" aria-hidden="true"></span>
						<span class="name">
							<span class="id">{j.plugin}<span class="sep">:</span>{j.job}</span>
							<span class="meta">{j.schedule} · {j.commandName}</span>
						</span>
						<span class="state {j.state}">{STATE_LABEL[j.state]}</span>
						{#if j.paused}<span class="badge">paused</span>{/if}
						<span class="when">
							{#if j.neverRan}
								no runs recorded
							{:else}
								{ago(j.lastFiredAt)} ago · {ms(j.lastDurationMs)}
							{/if}
						</span>
					</button>

					{#if j.state === 'failing' && j.lastError}
						<pre class="err">{j.lastError}</pre>
					{/if}
					{#if j.state === 'overdue' && j.overdueBySeconds !== null}
						<p class="warn">
							Scheduled for {j.nextFireAt} — {dur(j.overdueBySeconds)} ago. Wing advances the next
							fire time only when a run finishes, so a whole column of overdue jobs means the
							Pulse daemon is not firing.
						</p>
					{/if}
					{#if j.neverRan}
						<p class="warn">
							Registered {j.schedule}, never fired once.{#if j.paused}
								It is paused{#if j.pausedReason} — {j.pausedReason}{/if}.{:else}
								It is not paused, so nothing explains this.{/if}
						</p>
					{/if}
					{#if j.consecutiveFailures > 1}
						<p class="warn">{j.consecutiveFailures} consecutive failures.</p>
					{/if}

					{#if selected === j.id}
						<div class="runs">
							{#if j.envKeys.length > 0}
								<!-- Names only. Wing redacts the values at the source; publishing
								     them would hand every viewer the estate's credentials. -->
								<p class="envk">
									env: {j.envKeys.join(', ')}
									<span class="dim">(values redacted by Wing)</span>
								</p>
							{/if}
							{#if loadingRuns}
								<p class="note">Loading runs…</p>
							{:else if runsErr}
								<p class="bad">{runsErr}</p>
							{:else if runs.length === 0}
								<p class="note">No run rows exist for this job.</p>
							{:else}
								<table>
									<thead>
										<tr><th>fired</th><th>rc</th><th>took</th><th>actor</th></tr>
									</thead>
									<tbody>
										{#each runs as r (r.run_id)}
											<tr class:bad-row={r.exit_code !== null && r.exit_code !== 0}>
												<td>{r.fired_at}</td>
												<td>{r.exit_code === null ? '—' : r.exit_code}</td>
												<td>{ms(r.duration_ms)}</td>
												<td>{r.actor_id ?? '—'}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.pulse {
		font-size: 13px;
		color: var(--fg, #e8ecf3);
	}
	.note {
		color: var(--muted, #9aa4b2);
		padding: 10px 4px;
		line-height: 1.6;
	}
	.bad {
		color: #ffb4b4;
		padding: 10px 4px;
		line-height: 1.6;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		margin-bottom: 10px;
	}
	.c {
		font-size: 11px;
		padding: 2px 8px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.07);
		color: var(--muted, #9aa4b2);
	}
	.c.failing {
		background: rgba(255, 90, 90, 0.22);
		color: #ffc9c9;
	}
	.c.never {
		background: rgba(255, 170, 60, 0.22);
		color: #ffdca8;
	}
	.c.overdue {
		background: rgba(255, 210, 60, 0.18);
		color: #ffeeb0;
	}
	.win {
		margin-left: auto;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.row {
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.03);
	}
	.row.open {
		background: rgba(255, 255, 255, 0.07);
	}
	.head {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 10px;
		background: none;
		border: none;
		color: inherit;
		text-align: left;
		padding: 8px 10px;
		cursor: pointer;
		font-size: 13px;
	}
	.head:hover {
		background: rgba(255, 255, 255, 0.05);
		border-radius: 8px;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
		background: #5ec27a;
	}
	.dot.failing {
		background: #ff5a5a;
	}
	.dot.never {
		background: #ffaa3c;
	}
	.dot.overdue {
		background: #ffd23c;
	}
	.dot.running {
		background: #5a96ff;
	}
	.name {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
		flex: 1;
	}
	.id {
		font-weight: 600;
	}
	.sep {
		opacity: 0.4;
	}
	.meta {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		font-family: ui-monospace, monospace;
	}
	.state {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--muted, #9aa4b2);
	}
	.state.failing {
		color: #ffc9c9;
	}
	.state.never {
		color: #ffdca8;
	}
	.state.overdue {
		color: #ffeeb0;
	}
	.badge {
		font-size: 9px;
		text-transform: uppercase;
		border: 1px solid currentColor;
		border-radius: 4px;
		padding: 0 4px;
		opacity: 0.7;
	}
	.when {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		white-space: nowrap;
	}
	.err {
		margin: 0 10px 8px 28px;
		padding: 8px;
		background: rgba(255, 90, 90, 0.1);
		border-radius: 6px;
		font-size: 11px;
		font-family: ui-monospace, monospace;
		white-space: pre-wrap;
		overflow-x: auto;
		max-height: 9em;
	}
	.warn {
		margin: 0 10px 8px 28px;
		font-size: 11px;
		color: #ffdca8;
		line-height: 1.5;
	}
	.runs {
		padding: 4px 10px 10px 28px;
	}
	.envk {
		margin: 0 0 8px;
		font-size: 11px;
		font-family: ui-monospace, monospace;
		color: var(--muted, #9aa4b2);
		word-break: break-word;
	}
	.dim {
		opacity: 0.6;
	}
	.runs table {
		width: 100%;
		border-collapse: collapse;
		font-size: 11px;
		font-family: ui-monospace, monospace;
	}
	.runs th {
		text-align: left;
		color: var(--muted, #9aa4b2);
		font-weight: 500;
		padding: 2px 6px;
	}
	.runs td {
		padding: 2px 6px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}
	.bad-row td {
		color: #ffc9c9;
	}
</style>
