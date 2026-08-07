<!--
  Runs view — the run screen: the loop ledger, judge rings, and replay.

  THE SPOKES ARE EXECUTIONS, NOT WORKERS (operator refinement, 2026-08-06).
  Each verdict renders as a ring whose spokes are the judges the COMMITTED
  gate set declares — the denominator is the recorded scope, never the row
  count, so a judge that never got a row shows as an unaccounted gap. Three
  spoke states minimum: judged-good, judged-bad, NOT JUDGED — and the third
  is hatched, visually distinct from both, because "skips are not agreements"
  and absence must not render as either verdict.

  "LIVE" MEANS POLLING AND SAYS SO. Nothing in this estate streams; this view
  polls at 10 s while a judge run is in flight, 60 s otherwise, and stamps
  "polled Ns ago" instead of pretending to stream.

  THE ONE WRITE is the run-a-gate-set button (/bff/loop/judge). Its refusals
  are enumerated ON the screen — what this surface will not do is part of
  what it shows. Everything else is read-only.

  NAMED MISSING (each becomes live on the converge that redeploys its owner):
    - pulse_runs time-window params (Wing `since`/`until`) — replay beyond the
      last 25 runs per job needs them; the cursor below is honest about its
      window.
    - the deployed Wing lags the repo generally; the loop ledger reads are
      BONE surfaces and ship with the Bone restart instead.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import graphRaw from '$lib/anatomy/anatomy-graph.json';
	import { projectGraph, governingParagraphs } from '$lib/anatomy/graph';
	import { verdictRing, arcs, arcPath, tally, headroom, type Ring } from '$lib/anatomy/rings';
	import { loadLoop, runGateSet, judgeStatus, type LoopResponse } from '$lib/api/loop';
	import { loadRuns, type PulseRunRow } from '$lib/api/pulse';
	import { StatusNote, Badge, StateDot, exitTone } from '$lib/components/ui';

	interface Props {
		onfollowthread?: (actionId: string) => void;
	}
	let { onfollowthread }: Props = $props();

	const graph = projectGraph(graphRaw);
	const gatesets = graph.nodes.filter((n) => n.kind === 'gateset');
	const judges = new Map(
		graph.nodes.filter((n) => n.kind === 'judge').map((n) => [n.id.slice('judge:'.length), n])
	);

	let data = $state<LoopResponse | null>(null);
	let err = $state('');
	let loading = $state(true);
	let polledAt = $state(0);
	let now = $state(Date.now());

	// One in-flight judge job at a time — the engine serialises anyway.
	let jobId = $state('');
	let jobState = $state('');
	let runMsg = $state('');

	async function refresh() {
		try {
			data = await loadLoop();
			err = '';
			polledAt = Date.now();
		} catch (e) {
			err = e instanceof Error ? e.message : 'could not reach the BFF';
		} finally {
			loading = false;
		}
		if (jobId) {
			try {
				const s = (await judgeStatus(jobId)) as { state?: string };
				jobState = s.state ?? 'unknown';
				if (jobState !== 'running' && jobState !== 'queued') jobId = '';
			} catch {
				jobState = 'unknown — a Bone restart loses in-flight state, never the verdict';
				jobId = '';
			}
		}
	}

	let timer: ReturnType<typeof setInterval> | undefined;
	let clock: ReturnType<typeof setInterval> | undefined;
	$effect(() => {
		clearInterval(timer);
		// 10 s while watching a run — cheap against Bone's read path — else 60 s.
		timer = setInterval(() => void refresh(), jobId ? 10_000 : 60_000);
	});
	onMount(() => {
		void refresh();
		clock = setInterval(() => (now = Date.now()), 1_000);
	});
	onDestroy(() => {
		clearInterval(timer);
		clearInterval(clock);
	});

	async function fire(gateSet: string) {
		runMsg = '';
		try {
			const r = (await runGateSet(gateSet)) as { job_id?: string };
			jobId = r.job_id ?? '';
			jobState = 'queued';
			runMsg = `202 — job ${jobId}. The engine records the runs; the verdict appears in the ledger below when sealed.`;
		} catch (e) {
			runMsg = e instanceof Error ? e.message : 'refused';
		}
	}

	/** Judge runs by uuid — a spoke carries the run's uuid as its id. */
	const runByUuid = $derived(new Map((data?.judgeRuns ?? []).map((r) => [r.uuid, r])));

	/**
	 * Weakness ids the ledger cites that no declared source answers to.
	 *
	 * The registry lives in the graph as `weakness:*` nodes (Bone's
	 * SOURCE_ORDER). Measured 2026-08-07: every proposal in the ledger cites
	 * `w1` or `w2`, which are pilot placeholders — so the first link of the
	 * lineage does not join, and the board says so rather than drawing it.
	 */
	const orphanWeaknesses = $derived.by(() => {
		const declared = new Set(
			graph.nodes
				.filter((n) => n.kind === 'weakness')
				.map((n) => n.id.slice('weakness:'.length))
		);
		const seen = new Set<string>();
		for (const p of data?.proposals ?? []) {
			const w = p.weakness_id;
			if (w && !declared.has(w) && !declared.has(w.replace(/^weakness:/, ''))) seen.add(w);
		}
		return [...seen].sort();
	});

	/** Judge-run count and verdict for one proposal — the part that joins. */
	function proposalChain(p: { id: number }) {
		const runs = (data?.judgeRuns ?? []).filter((r) => r.proposal_id === p.id).length;
		const v = (data?.verdicts ?? []).find((x) => x.proposal_id === p.id);
		return { runs, result: v?.result ?? null, verdictUuid: v?.uuid ?? null };
	}

	// ── verdict rings ──
	const rings = $derived(
		(data?.verdicts ?? [])
			.map((v) => {
				const gs = gatesets.find((g) => g.id === `gateset:${v.gate_set}`);
				const declared = (gs?.facts.judges as string[] | undefined) ?? [];
				return {
					verdict: v,
					ring: verdictRing(v, data?.judgeRuns ?? [], declared)
				};
			})
			.filter((x): x is { verdict: (typeof x)['verdict']; ring: Ring } => x.ring !== null)
	);

	let openVerdict = $state<string | null>(null);

	// ── replay: one job's recorded runs, cursor over the loaded window ──
	const pulseJobs = graph.nodes.filter((n) => n.kind === 'pulse').map((n) => n.id.slice(6));
	let replayJob = $state('');
	let replayRuns = $state<PulseRunRow[]>([]);
	let replayErr = $state('');
	let cursor = $state(1); // 0..1 over the loaded window
	async function loadReplay() {
		replayErr = '';
		replayRuns = [];
		cursor = 1;
		if (!replayJob) return;
		try {
			// Ask for the last 48 h. A deployed Wing that predates the window
			// params ignores them and answers its default — the hint above and
			// the loaded-count below state what actually came back.
			const since = new Date(Date.now() - 48 * 3600 * 1000).toISOString();
			const r = await loadRuns(replayJob, since);
			replayRuns = [...r.runs].sort((a, b) => a.fired_at.localeCompare(b.fired_at));
			replayErr = r.error ?? '';
		} catch (e) {
			replayErr = e instanceof Error ? e.message : 'could not load runs';
		}
	}
	const cursorTime = $derived.by(() => {
		if (replayRuns.length === 0) return null;
		const times = replayRuns.map((r) => Date.parse(r.fired_at)).filter((t) => !Number.isNaN(t));
		if (times.length === 0) return null;
		const min = Math.min(...times);
		const max = Math.max(...times);
		return min + (max - min) * cursor;
	});
	const visibleRuns = $derived(
		cursorTime === null
			? replayRuns
			: replayRuns.filter((r) => Date.parse(r.fired_at) <= cursorTime)
	);

	function agoS(t: number): string {
		return `${Math.max(0, Math.round((now - t) / 1000))}s`;
	}
</script>

<div class="runs">
	{#if loading}
		<StatusNote kind="loading">Reading the loop ledger…</StatusNote>
	{:else if err}
		<StatusNote kind="error" title="The face BFF did not answer">{err}</StatusNote>
	{:else if data && data.configured === false}
		<StatusNote kind="unwired" title="Not wired up">{data.note}</StatusNote>
	{:else if data?.error}
		<StatusNote kind="error" title="Bone did not answer">
			{data.error} — the ledger below was not read.
		</StatusNote>
	{:else if data}
		<header class="bar">
			<Badge tone="neutral">{data.counts?.proposals ?? 0} proposals</Badge>
			<Badge tone="neutral">{data.counts?.judgeRuns ?? 0} judge runs</Badge>
			<Badge tone="neutral">{data.counts?.verdicts ?? 0} verdicts</Badge>
			<span class="stamp">polled {agoS(polledAt)} ago · every {jobId ? 10 : 60}s — this is a poll, not a stream</span>
		</header>

		<section class="cols">
			<!-- ── the committed gate sets: the real definition, and the one write ── -->
			<div class="col">
				<h3>Gate sets — committed definition</h3>
				<p class="hint">
					Rendered from state/judge-sets.yml via the anatomy graph — the loop's
					own oracle, inside its own deny list. Running one is the screen's only
					write; it selects work by NAME and nothing else.
				</p>
				{#each gatesets as gs (gs.id)}
					{@const name = gs.id.slice('gateset:'.length)}
					{@const members = (gs.facts.judges as string[] | undefined) ?? []}
					{@const paragraphs = governingParagraphs(graph, [
						gs.id,
						...members.map((j) => `judge:${j}`)
					])}
					<div class="gateset">
						<div class="gshead">
							<code>{name}</code>
							{#if gs.facts.unattended}
								<button class="run" onclick={() => void fire(name)} disabled={!!jobId}>
									run ▸
								</button>
							{:else}
								<Badge tone="warn" outline>attended only</Badge>
							{/if}
						</div>
						<pre class="def">{members
								.map((j) => {
									const spec = judges.get(j);
									const argv = (spec?.facts.argv as string[] | undefined) ?? [];
									const mw = spec?.facts.min_work;
									return `${j}: ${argv.join(' ')}  # min_work ${mw}`;
								})
								.join('\n')}</pre>
						{#if paragraphs.length > 0}
							<!-- The constitution highlight: paragraphs this set's judges
							     CITE in their own blocks — measured by the resolver, not
							     curated. Hover a chip for the citing lines. -->
							<div class="law">
								{#each paragraphs as p (p.id)}
									<span
										class="lawchip"
										title={`${p.doc} — ${p.heading || p.section}\n` +
											p.citedBy.map((c) => `${c.node} (${c.via})`).join('\n')}
									>
										§{p.section}
									</span>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
				{#if jobId || jobState}
					<p class="jobstate">
						judge job: <code>{jobId || '—'}</code> · {jobState}
					</p>
				{/if}
				{#if runMsg}<p class="runmsg">{runMsg}</p>{/if}
				<details class="refusals">
					<summary>what this button refuses</summary>
					<ul>
						<li>any body key other than <code>gate_set</code> → 400 (refused, not stripped)</li>
						<li><code>proposal_uuid</code> is never forwarded — judging a proposal is the engine's ceremony</li>
						<li>sets declared <code>unattended: false</code> → 409 (attended-host judges)</li>
						<li>callers below Tier-1 → 403, re-checked server-side</li>
						<li>no parameter can supply, hint at, or override a result — Bone's contract, not a UI choice</li>
					</ul>
				</details>
			</div>

			<!-- ── verdict rings: spokes are executions ── -->
			<div class="col">
				<h3>Verdicts — each ring one sealed run</h3>
				<p class="hint">
					Spokes are the judges the set DECLARES. Hatched = not judged
					(indeterminate / skipped, with its reason); hollow = recorded scope
					with no row. Neither is a pass and neither is a failure.
				</p>
				{#if rings.length === 0}
					<StatusNote kind="empty" title="No verdicts sealed yet">
						The ledger answered and holds no sealed verdict — a real result.
					</StatusNote>
				{/if}
				<div class="ringgrid">
					{#each rings as { verdict, ring: r } (verdict.uuid)}
						{@const t = tally(r)}
						<button
							class="ringcard"
							class:open={openVerdict === verdict.uuid}
							onclick={() => (openVerdict = openVerdict === verdict.uuid ? null : verdict.uuid)}
						>
							<svg viewBox="-60 -60 120 120" class="ringsvg" aria-label="{r.label}: {t.good} good, {t.bad} bad, {t.unjudged} not judged, {t.unaccounted} unaccounted of {t.declared}">
								<defs>
									<pattern id="hatch-{verdict.uuid}" patternUnits="userSpaceOnUse" width="4" height="4" patternTransform="rotate(45)">
										<line x1="0" y1="0" x2="0" y2="4" stroke="var(--warn, #e2b93b)" stroke-width="1.4" />
									</pattern>
								</defs>
								{#each arcs(r) as a, i (i)}
									<path
										d={arcPath(0, 0, 34, 52, a.startAngle, a.endAngle)}
										class="spoke {a.spoke?.state ?? 'unaccounted'}"
										fill={a.spoke?.state === 'unjudged' ? `url(#hatch-${verdict.uuid})` : undefined}
									>
										<title>
											{a.spoke
												? `${a.spoke.label}: ${a.spoke.state}${a.spoke.reason ? ' — ' + a.spoke.reason : ''}`
												: 'declared by the set, no row recorded — unaccounted, not passed'}
										</title>
									</path>
								{/each}
								<text class="ringresult {verdict.result}" x="0" y="4">{verdict.result}</text>
							</svg>
							<span class="ringlabel">{r.label}</span>
							<span class="ringmeta">{verdict.created_at} · {t.good}✓ {t.bad}✗ {t.unjudged}◍{#if t.unaccounted > 0}
									· {t.unaccounted} unaccounted{/if}</span>
						</button>
						{#if openVerdict === verdict.uuid}
							<ul class="spokelist">
								{#each r.spokes as s (s.id)}
									{@const run = runByUuid.get(s.id)}
									<li>
										<span class="sstate {s.state}">{s.state === 'unjudged' ? 'not judged' : s.state}</span>
										{s.label}
										{#if s.reason}<span class="sreason">— {s.reason}</span>{/if}
										{#if run && run.work_count !== null && run.min_work !== null && run.min_work > 0}
											{@const head = headroom(run.work_count, run.min_work)}
											<!--
											  RATCHET HEADROOM. The runner already refuses to call a
											  below-floor run a pass (judges.py:1353 → INDETERMINATE),
											  so this is not a correctness display — it is the LEADING
											  indicator that one. This estate's ratchets have decayed
											  twice, both times by GROWTH: the floor stayed put while
											  the suite grew past it, so a run that had lost 14% of
											  its collection still cleared. A bar that shows a pass
											  sitting 1% above its own floor makes the next decay
											  visible before it fires.
											-->
											<span
												class="ratchet"
												class:tight={head.tight}
												title="{run.work_count} of floor {run.min_work} — {head.pct}% headroom"
											>
												<span class="fill" style="width:{head.fillPct}%"></span>
												<span class="floortick" style="left:{head.tickPct}%"></span>
											</span>
											<span class="rwork" class:tight={head.tight}>
												{run.work_count} / {run.min_work}
											</span>
										{/if}
									</li>
								{/each}
								{#if r.unaccounted > 0}
									<li class="sunacc">
										{r.unaccounted} declared member(s) have no run row — the gap is
										the finding, not noise.
									</li>
								{/if}
							</ul>
						{/if}
					{/each}
				</div>

				<h3>Proposals <span class="pcount">{(data.proposals ?? []).length}</span></h3>
				{#if (data.proposals ?? []).length === 0}
					<StatusNote kind="empty" title="No proposals">The ledger holds none.</StatusNote>
				{:else}
					{#if orphanWeaknesses.length > 0}
						<!--
						  THE CHAIN IS weakness → proposal → judges → verdict, and its FIRST
						  link does not join today. `loop_proposals.weakness_id` holds ids
						  like `w1` while the weakness registry (Bone's SOURCE_ORDER, in the
						  graph as weakness:* nodes) uses names like `weakness:corpus-diff`.
						  Every proposal in the ledger is from one pilot day, 2026-08-02.

						  Rendering a weakness column over those ids would draw a lineage
						  that does not exist. Naming the gap is the honest half of a board
						  whose other three columns do join.
						-->
						<p class="orphan">
							{orphanWeaknesses.length} weakness id(s) in the ledger resolve to no
							declared source — <code>{orphanWeaknesses.join(', ')}</code>. The
							lineage weakness → proposal is NOT drawn, because it does not join:
							the registry names sources like <code>weakness:corpus-diff</code>.
						</p>
					{/if}
					<ul class="props">
						{#each data.proposals ?? [] as p (p.uuid)}
							{@const chain = proposalChain(p)}
							<li class="prow" class:dim={openVerdict !== null && chain.verdictUuid !== openVerdict}>
								<code>{p.weakness_id}</code>
								<span class="pmeta">{p.intent_class} · {p.gate_set} · attempt {p.attempt_n} · {p.created_at}</span>
								<!--
								  The flow, inline: how many of the gate set's declared judges
								  reported, and what the verdict was. Dimming the rows outside
								  the opened verdict is variant C's move — one lineage lit, the
								  rest present but quiet, so the board reads as a path rather
								  than as a list.
								-->
								<span class="pflow">
									<span class="pstep">{chain.runs} judge run(s)</span>
									<span class="parrow">→</span>
									{#if chain.result}
										<span class="pverdict {chain.result}">{chain.result}</span>
									{:else}
										<span class="pverdict none">no verdict recorded</span>
									{/if}
								</span>
							</li>
						{/each}
					</ul>
				{/if}
			</div>

			<!-- ── replay: cursor over a windowed query ── -->
			<div class="col">
				<h3>Replay</h3>
				<p class="hint">
					A time cursor over the loaded window. Wing's <code>since/until</code>
					window params exist in the repo as of 2026-08-06 and this screen asks
					for them — but the DEPLOYED Wing honours them only after its next
					converge; until then it answers the unwindowed default and the count
					below is honest about what actually loaded.
				</p>
				<select bind:value={replayJob} onchange={() => void loadReplay()}>
					<option value="">choose a job…</option>
					{#each pulseJobs as id (id)}
						<option value={id}>{id}</option>
					{/each}
				</select>
				{#if replayErr}
					<StatusNote kind="error" block={false}>{replayErr}</StatusNote>
				{:else if replayJob && replayRuns.length === 0}
					<StatusNote kind="empty" block={false}>No run rows for this job.</StatusNote>
				{:else if replayRuns.length > 0}
					<input
						class="cursor"
						type="range"
						min="0"
						max="1"
						step="0.01"
						bind:value={cursor}
						aria-label="replay cursor"
					/>
					<table>
						<thead><tr><th>fired</th><th>rc</th><th></th></tr></thead>
						<tbody>
							{#each visibleRuns as r (r.run_id)}
								<tr>
									<td>{r.fired_at}</td>
									<td>
										<StateDot tone={exitTone(r.exit_code)} label={r.exit_code === null ? 'no result' : `exit ${r.exit_code}`} />
										{r.exit_code ?? '—'}
									</td>
									<td>
										{#if r.actor_action_id}
											<button class="follow" onclick={() => onfollowthread?.(r.actor_action_id as string)}>follow →</button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
					<p class="hint">
						{visibleRuns.length} of {replayRuns.length} loaded runs at cursor. The
						graph's edges say what should precede each run; that overlay is
						derived, not recorded, until dispatch annotation lands — so it is not
						drawn here yet.
					</p>
				{/if}
			</div>
		</section>
	{/if}
</div>

<style>
	.runs {
		font-size: 13px;
		color: var(--fg, #e8ecf3);
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		margin-bottom: 10px;
	}
	.stamp {
		margin-left: auto;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.cols {
		display: grid;
		grid-template-columns: 1fr 1.2fr 1fr;
		gap: 14px;
	}
	@media (max-width: 60rem) {
		.cols {
			grid-template-columns: 1fr;
		}
	}
	h3 {
		margin: 0 0 4px;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.hint {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		line-height: 1.5;
		margin: 0 0 8px;
	}
	.gateset {
		margin-bottom: 8px;
	}
	.gshead {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 2px;
	}
	.run {
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid var(--line, rgba(128, 128, 128, 0.4));
		border-radius: 6px;
		color: var(--fg, #e8ecf3);
		font-size: 11px;
		padding: 2px 8px;
		cursor: pointer;
	}
	.run:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.def {
		margin: 0;
		padding: 6px 8px;
		background: rgba(255, 255, 255, 0.04);
		border-radius: 6px;
		font-size: 10px;
		font-family: ui-monospace, monospace;
		overflow-x: auto;
	}
	.jobstate,
	.runmsg {
		font-size: 11px;
		margin: 6px 0 0;
	}
	.law {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 4px;
	}
	.lawchip {
		font-size: 10px;
		font-family: ui-monospace, monospace;
		padding: 1px 6px;
		border-radius: 999px;
		border: 1px solid var(--ok, #4cc38a);
		color: var(--ok, #4cc38a);
		opacity: 0.85;
		cursor: help;
	}
	.refusals {
		margin-top: 8px;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.refusals ul {
		margin: 4px 0 0;
		padding-left: 16px;
		line-height: 1.6;
	}
	.ringgrid {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		margin-bottom: 10px;
	}
	.ringcard {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		width: 140px;
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid var(--line, rgba(128, 128, 128, 0.25));
		border-radius: 8px;
		padding: 8px;
		color: inherit;
		cursor: pointer;
	}
	.ringcard.open {
		border-color: var(--accent, #6aa2ff);
	}
	.ringsvg {
		width: 104px;
		height: 104px;
	}
	.spoke.good {
		fill: var(--ok, #4cc38a);
	}
	.spoke.bad {
		fill: var(--bad, #ff6b6b);
	}
	.spoke.unjudged {
		stroke: var(--warn, #e2b93b);
		stroke-width: 0.6;
	}
	.spoke.unaccounted {
		fill: none;
		stroke: var(--muted, #9aa4b2);
		stroke-width: 0.6;
		opacity: 0.5;
	}
	.ringresult {
		font-size: 10px;
		text-anchor: middle;
		fill: var(--fg, #e8ecf3);
		font-family: ui-monospace, monospace;
	}
	.ringresult.fail {
		fill: var(--bad-ink, #ff6b6b);
	}
	.ringresult.pass {
		fill: var(--ok, #4cc38a);
	}
	.ringlabel {
		font-size: 10px;
		font-family: ui-monospace, monospace;
	}
	.ringmeta {
		font-size: 9px;
		color: var(--muted, #9aa4b2);
	}
	.spokelist {
		list-style: none;
		width: 100%;
		margin: 0 0 8px;
		padding: 6px 8px;
		background: rgba(255, 255, 255, 0.04);
		border-radius: 6px;
		font-size: 11px;
	}
	.sstate {
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-right: 4px;
	}
	.sstate.good {
		color: var(--ok, #4cc38a);
	}
	.sstate.bad {
		color: var(--bad-ink, #ff6b6b);
	}
	.sstate.unjudged {
		color: var(--warn-ink, #e2b93b);
	}
	.sreason {
		color: var(--muted, #9aa4b2);
	}
	/* The floor tick is the whole point of the bar: a fill that stops short of
	   it is a run that did less work than its own ratchet demands. It is drawn
	   over the fill so it can never be hidden by a bar that overshoots. */
	.ratchet {
		position: relative;
		display: inline-block;
		width: 74px;
		height: 6px;
		border-radius: 3px;
		background: rgba(255, 255, 255, 0.08);
		margin-left: 6px;
		vertical-align: middle;
	}
	.ratchet .fill {
		position: absolute;
		inset: 0 auto 0 0;
		border-radius: 3px;
		background: var(--ok, #5ec27a);
		opacity: 0.75;
	}
	.ratchet.tight .fill {
		background: var(--warn, #ffaa3c);
	}
	.ratchet .floortick {
		position: absolute;
		top: -2px;
		bottom: -2px;
		width: 2px;
		background: var(--fg, #e8ecf3);
		opacity: 0.75;
	}
	.rwork {
		color: var(--muted, #9aa4b2);
		font-size: 10px;
		margin-left: 4px;
	}
	.rwork.tight {
		color: var(--warn-ink, #e2b93b);
	}
	.sunacc {
		color: var(--warn-ink, #e2b93b);
	}
	.props {
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 11px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.pmeta {
		display: block;
		color: var(--muted, #9aa4b2);
		font-size: 10px;
	}
	.pcount {
		color: var(--muted, #9aa4b2);
		font-weight: 400;
	}
	/* One lineage lit, the rest present but quiet — the board reads as a path
	   rather than a list. Dimmed, never hidden: a row you cannot see is a row
	   you cannot count. */
	.prow {
		border-left: 2px solid transparent;
		padding-left: 6px;
		transition: opacity 120ms ease-out;
	}
	.prow.dim {
		opacity: 0.42;
	}
	.pflow {
		display: flex;
		gap: 6px;
		align-items: baseline;
		font-size: 10px;
		margin-top: 2px;
	}
	.pstep,
	.parrow {
		color: var(--muted, #9aa4b2);
	}
	.pverdict.pass {
		color: var(--ok-ink, #b6e8c6);
	}
	.pverdict.fail {
		color: var(--bad-ink, #ffc9c9);
	}
	.pverdict.indeterminate,
	.pverdict.none {
		color: var(--muted, #9aa4b2);
		border-bottom: 1px dashed var(--muted, #9aa4b2);
	}
	/* An unresolvable reference is a finding, so it is warn-toned and sits
	   above the list it qualifies rather than in a footnote below it. */
	.orphan {
		font-size: 10.5px;
		line-height: 1.5;
		color: var(--warn-ink, #ffdca8);
		background: var(--warn-soft, rgba(255, 170, 60, 0.18));
		border: 1px solid rgba(255, 170, 60, 0.35);
		border-radius: 8px;
		padding: 7px 9px;
		margin: 0 0 8px;
	}
	select {
		width: 100%;
		margin-bottom: 6px;
		background: rgba(255, 255, 255, 0.06);
		color: inherit;
		border: 1px solid var(--line, rgba(128, 128, 128, 0.4));
		border-radius: 6px;
		padding: 4px;
		font-size: 12px;
	}
	.cursor {
		width: 100%;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 11px;
		font-family: ui-monospace, monospace;
	}
	th {
		text-align: left;
		color: var(--muted, #9aa4b2);
		font-weight: 500;
		padding: 2px 4px;
	}
	td {
		padding: 2px 4px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}
	.follow {
		background: none;
		border: none;
		color: var(--accent, #6aa2ff);
		font-size: 10px;
		padding: 0;
		cursor: pointer;
	}
</style>
