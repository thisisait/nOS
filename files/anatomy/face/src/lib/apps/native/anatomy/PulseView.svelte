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
	import { StatusNote, Badge, StateDot, exitTone, type Tone } from '$lib/components/ui';

	interface Props {
		/** Handed an `actor_action_id` when the operator follows a run into the
		 *  Wing view. The shell owns what happens next; this view just offers. */
		onfollowthread?: (actionId: string) => void;
	}
	let { onfollowthread }: Props = $props();

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

	/** Job state → the shell's shared severity vocabulary. `ok` is the only
	 *  green; `never` and `overdue` are warnings, not decorations. */
	const STATE_TONE: Record<PulseState, Tone> = {
		failing: 'bad',
		never: 'warn',
		overdue: 'warn',
		running: 'info',
		ok: 'ok'
	};

	const jobs = $derived((data?.jobs ?? []) as PulseJobView[]);
	const counts = $derived(data?.counts);
</script>

<div class="pulse">
	{#if loading}
		<StatusNote kind="loading">Reading the job catalog…</StatusNote>
	{:else if err}
		<StatusNote kind="error" title="The face BFF did not answer">{err}</StatusNote>
	{:else if data && data.configured === false}
		<!-- A deployment fact, stated as one. Not an empty list. -->
		<StatusNote kind="unwired" title="Not wired up">{data.note}</StatusNote>
	{:else if data?.error}
		<StatusNote kind="error" title="Wing did not answer">
			{data.error} — nothing below was checked.
		</StatusNote>
	{:else}
		<header class="bar">
			<Badge tone="neutral">{counts?.total ?? 0} jobs</Badge>
			<Badge tone="bad" count={counts?.failing}>&nbsp;failing</Badge>
			<Badge tone="warn" count={counts?.never}>&nbsp;never ran</Badge>
			<Badge tone="warn" count={counts?.overdue}>&nbsp;overdue</Badge>
			<Badge tone="neutral" count={counts?.paused}>&nbsp;paused</Badge>
			<Badge tone="ok" count={counts?.ok}>&nbsp;ok</Badge>
			<span class="win">last {data?.windowHours ?? 24}h</span>
		</header>

		{#if jobs.length === 0}
			<StatusNote kind="empty" title="No registered jobs at all">
				Wing answered — this is a real result, not a loading state. If you expect jobs
				here, the plugin loader has not run.
			</StatusNote>
		{/if}

		<ul class="rows">
			{#each jobs as j (j.id)}
				<li class="row" class:open={selected === j.id}>
					<button class="head" onclick={() => void select(j.id)}>
						<StateDot tone={STATE_TONE[j.state]} label={STATE_LABEL[j.state]} />
						<span class="name">
							<span class="id">{j.plugin}<span class="sep">:</span>{j.job}</span>
							<span class="meta">{j.schedule} · {j.commandName}</span>
						</span>
						<span class="state {j.state}">{STATE_LABEL[j.state]}</span>
						{#if j.paused}<Badge tone="neutral" outline>paused</Badge>{/if}
						<span class="when">
							{#if j.neverRan}
								no runs recorded
							{:else}
								{ago(j.lastFiredAt)} ago · {ms(j.lastDurationMs)}
							{/if}
						</span>
					</button>

					{#if j.state === 'failing' && j.lastError}
						<pre class="stderr">{j.lastError}</pre>
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
								<StatusNote kind="loading" block={false}>Loading runs…</StatusNote>
							{:else if runsErr}
								<StatusNote kind="error" block={false}>{runsErr}</StatusNote>
							{:else if runs.length === 0}
								<StatusNote kind="empty" block={false}>
									No run rows exist for this job.
								</StatusNote>
							{:else}
								<table>
									<thead>
										<tr><th>fired</th><th>rc</th><th>took</th><th>actor</th><th></th></tr>
									</thead>
									<tbody>
										{#each runs as r (r.run_id)}
											<tr>
												<td>{r.fired_at}</td>
												<td>
													<StateDot
														tone={exitTone(r.exit_code)}
														label={r.exit_code === null
															? 'no result reported'
															: `exit ${r.exit_code}`}
													/>
													{r.exit_code === null ? '—' : r.exit_code}
												</td>
												<td>{ms(r.duration_ms)}</td>
												<td>{r.actor_id ?? '—'}</td>
												<td>
													{#if r.actor_action_id}
														<!-- The thread. Same value on the events this run
														     produced; following it is the reason Anatomy is
														     one app rather than three. -->
														<button
															class="follow"
															onclick={() => onfollowthread?.(r.actor_action_id as string)}
														>
															follow →
														</button>
													{/if}
												</td>
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
	/* Local status/badge/dot rules used to live here — six of them, in colours
	   this component picked for itself. They are now `$lib/components/ui`, so
	   the same severity looks the same in every app. */
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		margin-bottom: 10px;
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
		color: var(--bad-ink);
	}
	.state.never,
	.state.overdue {
		color: var(--warn-ink);
	}
	.when {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		white-space: nowrap;
	}
	/* `stderr`, not `err`: this is captured process OUTPUT, not the view's own
	   error state. The gate that checks for hand-rolled status classes caught
	   the old name, and it was right to — the two meanings had one word. */
	.stderr {
		margin: 0 10px 8px 28px;
		padding: 8px;
		background: var(--bad-soft);
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
		color: var(--warn-ink);
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
	.runs td :global(.dot) {
		vertical-align: middle;
		margin-right: 4px;
	}
	.follow {
		background: none;
		border: none;
		color: var(--accent, #6aa2ff);
		font-size: 10px;
		padding: 0;
	}
</style>
