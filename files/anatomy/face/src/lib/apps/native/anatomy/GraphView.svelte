<!--
  Graph view — the definition screen: the anatomy graph, rendered.

  READ-ONLY BY CONSTRUCTION. The graph is authored in manifests, compiled by
  tools/anatomy-graph-gen.py, reviewed in a diff. This screen is an n8n-LOOK,
  not an n8n: no drag-to-connect, no schedule field, nothing here writes.

  DATA IS BUILD-TIME. The artifact changes only when the repo changes, and the
  repo reaches this host by converge — the same converge that rebuilds the
  face. The footer states the generation source instead of pretending to be
  live. The only live data is the Pulse snapshot joined onto pulse: nodes
  (60 s poll, same cadence and endpoint as the Pulse view).

  The temporal-debt panel is the reason the screen exists: 4 of 5 nightly
  chain edges are PERMITTED to invert by their own declared budgets, and that
  fact used to live in cron comments nobody could sum.
-->
<script lang="ts">
	import { onMount, onDestroy, untrack } from 'svelte';
	import raw from '$lib/anatomy/anatomy-graph.json';
	import {
		projectGraph,
		temporalDebt,
		filterForCanvas,
		joinLive,
		mutexSpokes,
		governingParagraphs,
		serviceCoverage,
		nodeLabel,
		KIND_GLYPH,
		STATE_TONE,
		NODE_KINDS,
		type NodeKind,
		type GraphNode
	} from '$lib/anatomy/graph';
	import { layout } from '$lib/anatomy/graphLayout';
	import { loadPulse, type PulseResponse } from '$lib/api/pulse';
	import { Badge, StatusNote, StateDot } from '$lib/components/ui';

	const graph = projectGraph(raw);
	const debt = temporalDebt(graph);
	/** What the service layer of this graph does not know. Rendered above the
	 *  canvas, always — the artifact counted 38 unsurveyed services and 38
	 *  withheld layers, and until now neither number reached a pixel. */
	const coverage = serviceCoverage(graph);
	/** Claim→resource spokes, once: the artifact does not change at runtime. */
	const spokes = mutexSpokes(graph);

	// Default view: the wiring. Services + authentik registry rows are 106
	// mostly-leaf nodes; they stay one chip away rather than drowning the
	// canvas. `connectedOnly` keeps whatever kind is on honest — a node with
	// no visible edge is hidden, not floated as decoration.
	let visibleKinds = $state(
		new Set<NodeKind>(NODE_KINDS.filter((k) => k !== 'service' && k !== 'authentik'))
	);
	let connectedOnly = $state(true);
	let selected = $state<GraphNode | null>(null);

	interface Props {
		/** A node id the caller was already pointing at (the desktop widget's
		 *  click-through). Empty = no request. */
		focusNode?: string;
		/** Fired once the request has been honoured, so a second click on the
		 *  same node in the widget arrives as a new request rather than being
		 *  swallowed as "no change". */
		onclearfocus?: () => void;
	}
	let { focusNode = '', onclearfocus }: Props = $props();

	// Honour an inbound node request: select it, and switch its kind on if the
	// default filter hides it — arriving at a graph that does not contain what
	// you clicked is worse than not arriving. The body is untracked: it WRITES
	// `visibleKinds`, and an effect that also read it reactively would re-run
	// itself forever.
	$effect(() => {
		const want = focusNode;
		if (!want) return;
		untrack(() => {
			const node = graph.byId.get(want);
			if (node) {
				if (!visibleKinds.has(node.kind)) visibleKinds = new Set(visibleKinds).add(node.kind);
				selected = node;
			}
			onclearfocus?.();
		});
	});

	let pulse = $state<PulseResponse | null>(null);
	const POLL_MS = 60_000;
	let timer: ReturnType<typeof setInterval> | undefined;
	async function refresh() {
		try {
			pulse = await loadPulse();
		} catch {
			pulse = null; // the join renders "unmeasured", never "ok"
		}
	}
	onMount(() => {
		void refresh();
		timer = setInterval(() => void refresh(), POLL_MS);
	});
	onDestroy(() => clearInterval(timer));

	const live = $derived(
		joinLive(
			graph,
			(pulse?.jobs ?? []).map((j) => ({ id: j.id, state: j.state, neverRan: j.neverRan }))
		)
	);

	const view = $derived(filterForCanvas(graph, visibleKinds, connectedOnly));
	const placed = $derived(
		layout({
			nodes: view.nodes,
			edges: [...view.edges, ...view.spokes.map((s) => ({ from: s.node, to: s.resource }))]
		})
	);

	function toggleKind(k: NodeKind) {
		const next = new Set(visibleKinds);
		if (next.has(k)) next.delete(k);
		else next.add(k);
		visibleKinds = next;
		if (selected && !next.has(selected.kind)) selected = null;
	}

	// ── pan + zoom: viewBox drag / wheel. Movement under 4px stays a click —
	//    setPointerCapture on the canvas would steal the node buttons' clicks
	//    (the WM bug this codebase has met twice). ──
	let vb = $state({ x: 0, y: 0, w: 1200, h: 700 });
	let dragging = false;
	let moved = false;
	let last = { x: 0, y: 0 };
	function onPointerDown(e: PointerEvent) {
		dragging = true;
		moved = false;
		last = { x: e.clientX, y: e.clientY };
	}
	function onPointerMove(e: PointerEvent) {
		if (!dragging) return;
		const dx = e.clientX - last.x;
		const dy = e.clientY - last.y;
		if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
		if (!moved) return;
		const scale = vb.w / 1200;
		vb = { ...vb, x: vb.x - dx * scale, y: vb.y - dy * scale };
		last = { x: e.clientX, y: e.clientY };
	}
	function onPointerUp() {
		dragging = false;
	}
	function onWheel(e: WheelEvent) {
		e.preventDefault();
		const factor = e.deltaY > 0 ? 1.12 : 1 / 1.12;
		const w = Math.min(6000, Math.max(300, vb.w * factor));
		const h = (w * vb.h) / vb.w;
		vb = { x: vb.x + (vb.w - w) / 2, y: vb.y + (vb.h - h) / 2, w, h };
	}

	// KIND_GLYPH / STATE_TONE / nodeLabel moved into $lib/anatomy/graph.ts
	// (2026-08-07): the desktop widget renders the same node ids on a
	// different surface, and a second copy of the glyph table is how the same
	// node ends up wearing two icons.
	const label = nodeLabel;

	function edgePath(from: string, to: string): string {
		const a = placed.byId.get(from);
		const b = placed.byId.get(to);
		if (!a || !b) return '';
		const midX = (a.x + b.x) / 2;
		return `M ${a.x + 150} ${a.y + 12} C ${midX + 60} ${a.y + 12}, ${midX - 60} ${b.y + 12}, ${b.x} ${b.y + 12}`;
	}

	/**
	 * A flat-top hexagon 34 wide, 26 tall, sharing the node row's 24px height so
	 * a claim sits on the same baseline as everything it is claimed by.
	 * Computed once: the shape never varies, and re-deriving it per node per
	 * frame would be work in a render loop for a constant.
	 */
	const HEX_PATH = (() => {
		const w = 34,
			h = 26,
			cut = 9;
		return `M ${cut} 0 L ${w - cut} 0 L ${w} ${h / 2} L ${w - cut} ${h} L ${cut} ${h} L 0 ${h / 2} Z`;
	})();

	/** How many nodes claim this resource — the number the hexagon replaces. */
	function claimantCount(resourceId: string): number {
		return spokes.filter((s) => s.resource === resourceId).length;
	}

	/** Live pulse state per node id — 'unmeasured' when no snapshot. */
	function liveState(id: string): string | null {
		if (!id.startsWith('pulse:')) return null;
		return live.states.get(id) ?? (pulse ? 'unregistered' : 'unmeasured');
	}
</script>

<div class="graphview">
	<header class="bar">
		{#each NODE_KINDS as k (k)}
			<button
				class="chip"
				class:on={visibleKinds.has(k)}
				onclick={() => toggleKind(k)}
				aria-pressed={visibleKinds.has(k)}
			>
				{KIND_GLYPH[k]}
				{k}
				<span class="n">{graph.counts[`nodes_${k}`] ?? 0}</span>
			</button>
		{/each}
		<label class="chip toggle" class:on={connectedOnly}>
			<input type="checkbox" bind:checked={connectedOnly} />
			connected only
		</label>
	</header>

	<!--
	  The remainder, in words, above the canvas. `service 63` on the chip beside
	  a canvas drawing 20 of them was the whole problem: the producer published
	  the unsurveyed count honestly and the rendering dropped it, so a node
	  nobody had read looked exactly like a measured root.
	-->
	<p class="coverage" class:partial={coverage.withheld > 0}>
		<span class="glyph">{KIND_GLYPH.service}</span>
		{coverage.sentence}
	</p>

	{#if graph.warnings.length > 0}
		<!-- The union-kind feedback loop (the corpus-diff halt) — reviewed, not
		     refused, and therefore stated out loud here rather than absorbed. -->
		<div class="warnings">
			{#each graph.warnings as w (w)}
				<p class="warnline">⟳ {w}</p>
			{/each}
		</div>
	{/if}

	<div class="body">
		<div
			class="canvas"
			role="application"
			aria-label="Anatomy graph canvas — drag to pan, wheel to zoom"
			onpointerdown={onPointerDown}
			onpointermove={onPointerMove}
			onpointerup={onPointerUp}
			onpointerleave={onPointerUp}
			onwheel={onWheel}
		>
			<svg viewBox="{vb.x} {vb.y} {vb.w} {vb.h}" width="100%" height="100%">
				<!-- mutex spokes first (underneath): claim → resource, undirected -->
				{#each view.spokes as s (s.node + s.resource)}
					<path class="edge mutex" d={edgePath(s.node, s.resource)} />
				{/each}
				{#each view.edges as e (e.kind + e.from + e.to)}
					<path
						class="edge {e.kind}"
						class:invert={e.canInvert === true}
						d={edgePath(e.from, e.to)}
					/>
					{#if e.kind === 'temporal' && e.marginMin !== undefined}
						{@const a = placed.byId.get(e.from)}
						{@const b = placed.byId.get(e.to)}
						{#if a && b}
							<text
								class="marginlabel"
								class:invert={e.canInvert === true}
								x={(a.x + 150 + b.x) / 2}
								y={(a.y + b.y) / 2 + 8}
							>
								{e.marginMin}m{e.canInvert ? ' ⚠ can invert' : ''}
							</text>
						{/if}
					{/if}
				{/each}
				{#each placed.nodes as p (p.id)}
					{@const n = graph.byId.get(p.id)}
					{@const ls = liveState(p.id)}
					{#if n}
						<g
							class="node {n.kind}"
							class:selected={selected?.id === n.id}
							class:unsurveyed={n.dependencySurvey != null && n.dependencySurvey !== 'declared'}
							transform="translate({p.x},{p.y})"
							role="button"
							tabindex="0"
							aria-label="{n.kind} {label(n.id)}{n.layer
								? ` — ${n.layer}`
								: n.dependencySurvey && n.dependencySurvey !== 'declared'
									? ' — layer withheld, upstreams never surveyed'
									: ''}"
							onpointerdown={(ev) => ev.stopPropagation()}
							onclick={() => (selected = selected?.id === n.id ? null : n)}
							onkeydown={(ev) => {
								if (ev.key === 'Enter' || ev.key === ' ') {
									ev.preventDefault();
									selected = selected?.id === n.id ? null : n;
								}
							}}
						>
							{#if n.kind === 'resource'}
								<!--
								  A RESOURCE IS A CLAIM, not a node like the others, and drawing
								  it as one is what left the mutex layer unreadable: 56 pairwise
								  edges between things that are not connected to each other at
								  all — they share a claim. The hexagon says "this is the thing
								  being claimed", the count says by how many, and five shapes
								  then carry what fifty-six lines could not. Nothing is hidden:
								  the pairwise edges stay in the artifact and in the inspector.
								-->
								<path class="hex" d={HEX_PATH} />
								<text class="glyph" x="20" y="18">{KIND_GLYPH[n.kind]}</text>
								<text class="name" x="44" y="14">{label(n.id)}</text>
								<text class="claimants" x="44" y="25">{claimantCount(n.id)} claimants</text>
							{:else}
								<rect width="150" height="24" rx="6" />
								<text class="glyph" x="7" y="16">{KIND_GLYPH[n.kind]}</text>
								<text class="name" x="24" y="16">{label(n.id)}</text>
							{/if}
							{#if ls && ls !== 'unmeasured' && ls !== 'unregistered'}
								<circle class="dot {ls}" cx="140" cy="12" r="4" />
							{:else if ls}
								<text class="unmeasured" x="134" y="16">?</text>
							{/if}
						</g>
					{/if}
				{/each}
			</svg>
		</div>

		<aside class="side">
			{#if selected}
				{@const ls = liveState(selected.id)}
				<div class="inspector">
					<h3>{KIND_GLYPH[selected.kind]} {selected.id}</h3>
					<p class="desc">{selected.description}</p>
					<dl>
						<dt>anchor</dt>
						<dd>{selected.anchor}</dd>
						<dt>source</dt>
						<dd>{selected.source}</dd>
						{#if ls}
							<dt>live state</dt>
							<dd>
								{#if ls === 'unmeasured'}
									unmeasured — the Pulse snapshot did not load; this is not "ok"
								{:else if ls === 'unregistered'}
									declared in the repo, not registered in Wing — the next Wing converge closes this
								{:else}
									<StateDot tone={STATE_TONE[ls] ?? 'neutral'} label={ls} />
									{ls}
								{/if}
							</dd>
						{/if}
						{#each Object.entries(selected.facts) as [k, v] (k)}
							{#if v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0)}
								<dt>{k}</dt>
								<dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
							{/if}
						{/each}
					</dl>
					{#if selected.kind !== 'doctrine'}
						{@const laws = governingParagraphs(graph, [selected.id])}
						{#if laws.length > 0}
							<!--
							  GOVERNED BY — the written law that applies to this node, with its
							  heading, not just its number. A citation renders as prose because
							  a bare section number tells an operator nothing at 03:00, and because the whole
							  point of the doctrine layer is that a rule can be READ where it
							  binds rather than looked up in a document nobody opens.
							-->
							<h4>governed by</h4>
							{#each laws as law (law.id)}
								<div class="lawcard">
									<div class="p">§{law.section} · {law.doc.split('/').pop()}</div>
									<div class="q">{law.heading}</div>
									{#each law.citedBy as c (c.node + c.via)}
										<div class="cite">{c.via}{c.citations > 1 ? ` ×${c.citations}` : ''}</div>
									{/each}
								</div>
							{/each}
						{/if}
					{/if}

					{#if selected.kind === 'resource'}
						<!--
						  The hexagon collapses 56 pairwise edges into 5 claims. Collapsing is
						  only honest if the thing collapsed is still reachable, so the
						  claimants are listed here in full — the picture is a summary, this
						  is the denominator behind it.
						-->
						{@const mine = spokes.filter((s) => s.resource === selected!.id)}
						<h4>claimed by <span class="count">{mine.length}</span></h4>
						<ul class="edgelist">
							{#each mine as s (s.node)}
								<li><span class="ek mutex">claims</span> {s.node}</li>
							{/each}
						</ul>
						<p class="hint">
							These may never run at once. The pairwise mutex edges behind this claim stay in the
							artifact; the canvas draws the claim instead.
						</p>
					{/if}

					<h4>edges</h4>
					<ul class="edgelist">
						{#each graph.edges.filter((e) => e.from === selected!.id || e.to === selected!.id) as e (e.kind + e.from + e.to)}
							<li>
								<span class="ek {e.kind}">{e.kind}</span>
								{e.from === selected!.id ? `→ ${e.to}` : `← ${e.from}`}
								{#if e.via}<span class="via">{e.via}</span>{/if}
							</li>
						{/each}
					</ul>
				</div>
			{:else}
				<div class="debt">
					<h3>Temporal debt</h3>
					<p class="hint">
						margin the schedules declare, worst-case. A red row's own budgets already permit the
						ordering to flip — only real runtimes far below their ceilings keep the chain ordered
						tonight.
					</p>
					<table>
						<thead>
							<tr><th>edge</th><th>measured</th><th>declared</th></tr>
						</thead>
						<tbody>
							{#each debt as r (r.from + r.to)}
								<tr class:invert={r.canInvert}>
									<td>{label(r.from)} → {label(r.to)}</td>
									<td>{r.marginMin ?? '—'}m</td>
									<td>
										{r.declaredMarginMin ?? '—'}m
										{#if r.canInvert}<Badge tone="bad" outline>can invert</Badge>{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>

					{#if live.unregistered.length > 0 && pulse}
						<h3>Declared, not registered</h3>
						<p class="hint">
							In the repo's manifests but absent from Wing's catalog — the wiring ships on the next
							Wing converge.
						</p>
						<ul class="plain">
							{#each live.unregistered as id (id)}<li>{id}</li>{/each}
						</ul>
					{/if}
					{#if live.neverRan.length > 0}
						<h3>Registered, never ran</h3>
						<ul class="plain">
							{#each live.neverRan as id (id)}<li>{id}</li>{/each}
						</ul>
					{/if}
					{#if !pulse}
						<StatusNote kind="unwired" title="Live join unmeasured">
							The Pulse snapshot did not load, so live states are unknown — unknown, not healthy.
						</StatusNote>
					{/if}
				</div>
			{/if}
		</aside>
	</div>

	<footer class="src">
		{graph.counts.nodes} nodes · {graph.counts.edges} edges · compiled by tools/anatomy-graph-gen.py from
		the manifests — data is as fresh as the last converge, and says so rather than pretending to stream.
	</footer>
</div>

<style>
	.graphview {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		font-size: 13px;
		color: var(--fg, #e8ecf3);
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-bottom: 8px;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		padding: 3px 8px;
		border-radius: 999px;
		border: 1px solid var(--line, rgba(128, 128, 128, 0.35));
		background: none;
		color: var(--muted, #9aa4b2);
		cursor: pointer;
	}
	.chip.on {
		color: var(--fg, #e8ecf3);
		background: rgba(255, 255, 255, 0.08);
	}
	.chip .n {
		font-variant-numeric: tabular-nums;
		opacity: 0.6;
	}
	.toggle input {
		margin: 0 2px 0 0;
	}
	.coverage {
		margin: 0 0 6px;
		font-size: 11px;
		font-family: ui-monospace, monospace;
		color: var(--muted-ink, rgba(190, 190, 190, 0.75));
	}
	.coverage.partial {
		color: var(--warn-ink, #ffaa3c);
	}
	.coverage .glyph {
		margin-right: 4px;
	}
	.warnings {
		margin: 0 0 6px;
	}
	.warnline {
		margin: 0;
		font-size: 11px;
		color: var(--warn-ink);
		font-family: ui-monospace, monospace;
	}
	.body {
		flex: 1;
		min-height: 0;
		display: flex;
		gap: 10px;
	}
	.canvas {
		flex: 1;
		min-width: 0;
		border: 1px solid var(--line, rgba(128, 128, 128, 0.25));
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.02);
		cursor: grab;
		touch-action: none;
	}
	.canvas:active {
		cursor: grabbing;
	}
	.edge {
		fill: none;
		stroke-width: 1.2;
	}
	.edge.data {
		stroke: var(--accent, #6aa2ff);
		opacity: 0.75;
	}
	.edge.trigger {
		stroke: var(--muted, #9aa4b2);
		stroke-dasharray: 2 3;
		opacity: 0.45;
	}
	.edge.temporal {
		stroke: var(--warn-ink, #e2b93b);
		stroke-dasharray: 6 4;
		opacity: 0.8;
	}
	.edge.temporal.invert {
		stroke: var(--bad-ink, #ff6b6b);
	}
	.edge.mutex {
		stroke: var(--muted, #9aa4b2);
		stroke-width: 2.2;
		stroke-dasharray: 1 4;
		opacity: 0.25;
	}
	/* the constitution: which paragraphs govern this node */
	.edge.governed_by {
		stroke: var(--ok, #4cc38a);
		stroke-dasharray: 4 2;
		opacity: 0.5;
	}
	.marginlabel {
		font-size: 9px;
		fill: var(--warn-ink, #e2b93b);
	}
	.marginlabel.invert {
		fill: var(--bad-ink, #ff6b6b);
	}
	.node rect {
		fill: rgba(255, 255, 255, 0.06);
		stroke: var(--line, rgba(128, 128, 128, 0.4));
	}
	.node:hover rect,
	.node.selected rect {
		fill: rgba(255, 255, 255, 0.14);
		stroke: var(--accent, #6aa2ff);
	}
	/* A service nobody has surveyed for upstreams is drawn OPEN. It carries no
	   `layer` — the derivation refuses to answer from an absence of evidence
	   (docs/doctrine/layers.md §4.2) — and until this outline existed it was
	   the same solid rectangle as a service that had been measured. */
	.node.unsurveyed rect {
		stroke-dasharray: 3 3;
		fill: none;
	}
	/* A claim is warn-toned, not neutral: it is the one node kind that
	   constrains when other things may run, and the colour says "this is a
	   constraint" without claiming anything is wrong. */
	.node .hex {
		fill: var(--warn-soft, rgba(255, 170, 60, 0.18));
		stroke: var(--warn, #ffaa3c);
		stroke-width: 1.2;
	}
	.node:hover .hex,
	.node.selected .hex {
		fill: rgba(255, 170, 60, 0.32);
	}
	.node:focus-visible .hex {
		stroke-width: 2;
	}
	.node .claimants {
		fill: var(--muted, #9aa4b2);
		font-size: 8.5px;
	}
	.node {
		cursor: pointer;
		outline: none;
	}
	.node:focus-visible rect {
		stroke: var(--accent, #6aa2ff);
		stroke-width: 2;
	}
	.node text {
		fill: var(--fg, #e8ecf3);
		font-size: 10px;
		font-family: ui-monospace, monospace;
	}
	.node .glyph {
		font-size: 11px;
	}
	.node .name {
		font-size: 10px;
	}
	.node .unmeasured {
		fill: var(--muted, #9aa4b2);
	}
	.dot.ok {
		fill: var(--ok, #4cc38a);
	}
	.dot.failing {
		fill: var(--bad, #ff6b6b);
	}
	.dot.never,
	.dot.overdue,
	.dot.findings {
		fill: var(--warn, #e2b93b);
	}
	.dot.running {
		fill: var(--info, #6aa2ff);
	}
	.side {
		width: 340px;
		flex-shrink: 0;
		overflow: auto;
		border: 1px solid var(--line, rgba(128, 128, 128, 0.25));
		border-radius: 8px;
		padding: 10px;
		background: rgba(255, 255, 255, 0.02);
	}
	.inspector h3,
	.debt h3 {
		margin: 0 0 6px;
		font-size: 12px;
	}
	.debt h3 + .hint {
		margin-top: 0;
	}
	.inspector .desc {
		font-size: 12px;
		line-height: 1.5;
		margin: 0 0 8px;
	}
	.inspector dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px 8px;
		font-size: 11px;
		margin: 0 0 8px;
	}
	.inspector dt {
		color: var(--muted, #9aa4b2);
	}
	.inspector dd {
		margin: 0;
		font-family: ui-monospace, monospace;
		word-break: break-word;
	}
	.inspector h4 {
		margin: 8px 0 4px;
		font-size: 11px;
		color: var(--muted, #9aa4b2);
	}
	.edgelist {
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 11px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.ek {
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-right: 4px;
	}
	.ek.data {
		color: var(--accent, #6aa2ff);
	}
	.ek.temporal {
		color: var(--warn-ink);
	}
	.ek.trigger,
	.ek.mutex {
		color: var(--muted, #9aa4b2);
	}
	.via {
		display: block;
		color: var(--muted, #9aa4b2);
		font-size: 10px;
		margin-left: 2px;
	}
	.hint {
		font-size: 11px;
		color: var(--muted, #9aa4b2);
		line-height: 1.5;
	}
	/* The law reads as a quotation, because that is what it is. Info-toned so
	   it cannot be mistaken for a warning: a rule that applies is not a fault. */
	.lawcard {
		border: 1px solid rgba(90, 150, 255, 0.3);
		background: var(--info-soft, rgba(90, 150, 255, 0.16));
		border-radius: 10px;
		padding: 8px 10px;
		margin-bottom: 6px;
	}
	.lawcard .p {
		font-family: ui-monospace, monospace;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.06em;
		color: var(--info-ink, #bcd4ff);
	}
	.lawcard .q {
		font-size: 11.5px;
		font-style: italic;
		color: var(--fg, #e8ecf3);
		margin-top: 4px;
		line-height: 1.45;
	}
	.lawcard .cite {
		font-family: ui-monospace, monospace;
		font-size: 9.5px;
		color: var(--muted, #9aa4b2);
		margin-top: 4px;
		word-break: break-all;
	}
	.debt table {
		width: 100%;
		border-collapse: collapse;
		font-size: 11px;
		font-family: ui-monospace, monospace;
	}
	.debt th {
		text-align: left;
		color: var(--muted, #9aa4b2);
		font-weight: 500;
		padding: 2px 4px;
	}
	.debt td {
		padding: 2px 4px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}
	.debt tr.invert td {
		color: var(--bad-ink);
	}
	.plain {
		list-style: none;
		margin: 0 0 8px;
		padding: 0;
		font-size: 11px;
		font-family: ui-monospace, monospace;
	}
	.src {
		margin-top: 8px;
		font-size: 10px;
		color: var(--muted, #9aa4b2);
	}
</style>
