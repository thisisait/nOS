<!--
  Anatomy at a glance — the first WIDGET (form=widget, build=F1).

  WHAT IT IS. A small always-on desktop surface showing seven nodes of the
  anatomy graph and the edges between them, with the live Pulse state joined
  onto the scheduled-job nodes. Clicking a node opens the Anatomy app's Graph
  view with that node already selected. A widget is not a window: it has no
  titlebar, no chrome, no scroll, and `launchNative('anatomy-widget')` refuses
  to open one.

  THE SEVEN NODES ARE REAL AND THEY ARE CHOSEN BY A STATED RULE. They are read
  from the same `src/lib/anatomy/anatomy-graph.json` the Graph view uses —
  same ids, kinds, anchors, descriptions — and selected by
  `spotlight()`: the highest-degree nodes with mutex pairs excluded, ties by
  id. The rule is printed under the picture, because a seven-node sample of a
  190-odd-node graph is a claim about WHICH seven and the operator is entitled
  to check it. Seven invented nodes would be decoration; this is a projection.

  HONESTY RULES, the same ones every other surface here obeys:
    * No `[live]` badge. The graph is a BUILD-TIME artifact (it changes only
      when the repo changes, and the repo arrives by converge) and the Pulse
      overlay is a 60 s POLL. The footer says exactly that, in those words.
    * Four distinct states for the overlay — loading / unwired / unreachable /
      nothing to report — never collapsed into one grey line. A node with no
      live row renders `unmeasured`, which is a fifth thing again and is NOT
      ok-green.
    * `--ok` green is not the resting state. A quiet estate shows neutral.
    * Tier-1 only, and for everyone else the widget renders NOTHING at all —
      not an error, not a placeholder. Same decision as the menubar: the
      operational internals of the estate are administrator information, and a
      permanent red box in a tier-3 user's corner teaches everyone to ignore
      corners.

  THE RECURSION IS THE POINT. This widget is itself a node in the graph it
  draws — `faceapp:anatomy-widget`, emitted by tools/anatomy-graph-gen.py from
  the registry entry below, with edges to the face that hosts it, the Anatomy
  view it opens, and the Wing daemon whose Pulse state it reads. It is usually
  not among the seven (its degree is 3), and it is not promoted there: the
  rule picks the nodes, not the author.
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import raw from '$lib/anatomy/anatomy-graph.json';
	import {
		projectGraph,
		spotlight,
		joinLive,
		nodeLabel,
		KIND_GLYPH,
		STATE_TONE
	} from '$lib/anatomy/graph';
	import { layout, PAD, ROW_H } from '$lib/anatomy/graphLayout';
	import { loadPulse, type PulseResponse } from '$lib/api/pulse';
	import { requestAnatomy } from '$lib/anatomy/focus';
	import { launchNative } from '$lib/apps/native';
	import { focusApp } from '$lib/stores/desktop';
	import { canViewAnatomy } from '$lib/security/tier';
	import { StatusNote, StateDot, toneVars, type Tone } from '$lib/components/ui';
	import type { Identity } from '$lib/contracts';

	interface Props {
		/** The BFF-derived identity, handed down by the widget layer. Chrome
		 *  gate only — every endpoint behind this re-checks the tier itself. */
		identity?: Identity;
	}
	let { identity }: Props = $props();

	// Build-time, once: the artifact does not change while the page is open.
	const graph = projectGraph(raw);
	const spot = spotlight(graph, 7);
	const placed = layout({ nodes: spot.nodes, edges: spot.edges });

	/** This widget's own node, when the generator has emitted it. `null` says
	 *  so out loud rather than quietly dropping the line — the recursion is a
	 *  claim, and an unbacked claim should be visible. */
	const selfNode = graph.byId.get('faceapp:anatomy-widget') ?? null;
	/** Its degree in the same ranking the seven came from — stated, so "not
	 *  among these seven" is a measurement rather than modesty. */
	const selfDegree = graph.edges.filter(
		(e) => e.kind !== 'mutex' && (e.from === selfNode?.id || e.to === selfNode?.id)
	).length;

	// ── the live overlay ─────────────────────────────────────────────────────
	// Four states, deliberately not interchangeable (see $lib/components/ui/tone.ts):
	//   asking      — we have not had an answer yet
	//   unwired     — the Wing token is not set; nothing was checked
	//   unreachable — we asked and got no usable answer
	//   answered    — we have a snapshot (which may itself hold zero jobs)
	type Phase = 'asking' | 'unwired' | 'unreachable' | 'answered';
	let phase = $state<Phase>('asking');
	let note = $state('');
	let pulse = $state<PulseResponse | null>(null);

	const POLL_MS = 60_000;
	let timer: ReturnType<typeof setInterval> | undefined;

	async function refresh() {
		try {
			const r = await loadPulse();
			if (r.configured === false) {
				phase = 'unwired';
				note = r.note ?? 'The Wing API token is not set on the face container.';
				pulse = null;
				return;
			}
			if (r.error) {
				phase = 'unreachable';
				note = r.error;
				// Keep the previous snapshot: blanking it would read as "the
				// jobs went away", which is a different and much calmer claim.
				return;
			}
			pulse = r;
			phase = 'answered';
			note = '';
		} catch (e) {
			phase = 'unreachable';
			note = e instanceof Error ? e.message : 'the Pulse projection did not answer';
		}
	}

	const mayView = $derived(canViewAnatomy(identity?.groups));

	onMount(() => {
		if (!mayView) return;
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

	/** The live state of one node, or null when the node is not a pulse job.
	 *  `unmeasured` when we have no snapshot; `unregistered` when we have one
	 *  and the job is not in it (declared but never registered). */
	function stateOf(id: string): string | null {
		if (!id.startsWith('pulse:')) return null;
		if (phase !== 'answered') return 'unmeasured';
		return live.states.get(id) ?? 'unregistered';
	}

	/** Tone for a node dot. Anything not in STATE_TONE is neutral — an unknown
	 *  or unmeasured state must never borrow green. */
	function toneOf(id: string): Tone {
		const s = stateOf(id);
		return (s && STATE_TONE[s]) || 'neutral';
	}

	function open(id: string) {
		requestAnatomy('graph', undefined, id);
		if (!focusApp('anatomy')) launchNative('anatomy');
	}

	// ── geometry ─────────────────────────────────────────────────────────────
	// PLACEMENT IS NOT RE-IMPLEMENTED. `layout()` (the same layered DAG pass
	// the Graph view uses, deterministic by design) decides rank and row; only
	// the pitch is widget-sized here, so a node never lands in one place on
	// the canvas and a different place in the corner.
	const RANK_W = 148;
	const ROW_PITCH = 26;
	const NODE_W = 134;
	const NODE_H = 20;

	/** Label clipped to the box, with an ellipsis so a clipped id is visibly
	 *  clipped. Without it `cortex:cortex-fs` reads as a complete id that does
	 *  not exist — the full one is in the tooltip and one click away. */
	function short(id: string): string {
		const l = nodeLabel(id);
		return l.length > 17 ? l.slice(0, 17) + '…' : l;
	}

	/** What the tooltip and the screen reader get: the full id, the node's own
	 *  one-line body, its live state, and the DEGREE that put it here. The
	 *  degree is the ranking criterion, so it must be checkable — it is off
	 *  the canvas for room, not withheld. */
	function detail(id: string, description: string): string {
		const s = stateOf(id);
		return `${id} — ${description}${s ? ` — state: ${s}` : ''} — degree ${spot.degree.get(id) ?? 0}`;
	}

	const pos = new Map(
		placed.nodes.map((p) => [
			p.id,
			{ x: p.rank * RANK_W, y: ((p.y - PAD) / ROW_H) * ROW_PITCH }
		])
	);
	const VB = {
		w: Math.max(...[...pos.values()].map((p) => p.x + NODE_W), NODE_W),
		h: Math.max(...[...pos.values()].map((p) => p.y + NODE_H), NODE_H)
	};

	function edgePath(from: string, to: string): string {
		const a = pos.get(from);
		const b = pos.get(to);
		if (!a || !b) return '';
		const midX = (a.x + NODE_W + b.x) / 2;
		return `M ${a.x + NODE_W} ${a.y + NODE_H / 2} C ${midX} ${a.y + NODE_H / 2}, ${midX} ${b.y + NODE_H / 2}, ${b.x} ${b.y + NODE_H / 2}`;
	}

	const EDGE_STROKE: Record<string, string> = {
		data: 'var(--accent)',
		trigger: 'var(--info)',
		temporal: 'var(--warn)',
		governed_by: 'var(--muted)'
	};
</script>

{#if mayView}
	<section class="widget glass" aria-label="Anatomy at a glance">
		<header>
			<span class="ttl"><span aria-hidden="true">🫀</span> Anatomy</span>
			<span class="grow"></span>
			{#if phase === 'answered'}
				<StateDot
					tone="neutral"
					label="{live.states.size} scheduled job(s) matched to a graph node"
				/>
			{/if}
		</header>

		<svg
			viewBox="0 0 {VB.w} {VB.h}"
			role="img"
			aria-label="{spot.nodes.length} nodes of the anatomy graph and {spot.edges
				.length} edges between them"
		>
			{#each spot.edges as e (e.kind + e.from + e.to)}
				<path
					d={edgePath(e.from, e.to)}
					fill="none"
					stroke={EDGE_STROKE[e.kind] ?? 'var(--muted)'}
					stroke-width="1.5"
					opacity="0.55"
				/>
			{/each}
			{#each spot.nodes as n (n.id)}
				{@const p = pos.get(n.id)}
				{#if p}
					<g
						class="node"
						transform="translate({p.x},{p.y})"
						role="button"
						tabindex="0"
						aria-label="{detail(n.id, n.description)} — open in the Anatomy graph"
						onclick={() => open(n.id)}
						onkeydown={(ev) => {
							if (ev.key === 'Enter' || ev.key === ' ') {
								ev.preventDefault();
								open(n.id);
							}
						}}
					>
						<title>{detail(n.id, n.description)}</title>
						<rect width={NODE_W} height={NODE_H} rx="5" />
						<circle cx="9" cy={NODE_H / 2} r="3" fill={toneVars(toneOf(n.id)).solid} />
						<text x="17" y={NODE_H / 2 + 3.5}>{KIND_GLYPH[n.kind]} {short(n.id)}</text>
					</g>
				{/if}
			{/each}
		</svg>

		<!-- The overlay's state, never folded into the picture. -->
		{#if phase === 'asking'}
			<StatusNote kind="loading" block={false}>asking Pulse…</StatusNote>
		{:else if phase === 'unwired'}
			<StatusNote kind="unwired" block={false}>{note} Nothing was checked.</StatusNote>
		{:else if phase === 'unreachable'}
			<StatusNote kind="error" block={false}>Pulse unreachable: {note}</StatusNote>
		{:else if live.states.size === 0}
			<StatusNote kind="empty" block={false}>
				no scheduled job matched a node here — the states below are unmeasured, not ok
			</StatusNote>
		{/if}

		<footer>
			<p class="rule">
				showing {spot.rule} — {spot.nodes.length} of {graph.counts.nodes ?? 0} nodes,
				{spot.edges.length} induced edge(s), {spot.components} component(s). Hover a box for its
				full id, body, state and degree.
			</p>
			<p class="prov">
				graph: build-time artifact ({graph.counts.nodes ?? 0} nodes, regenerated by
				tools/anatomy-graph-gen.py at converge) · pulse state: polled every 60 s
			</p>
			<p class="self">
				{#if selfNode}
					this widget is <button class="link" onclick={() => open(selfNode.id)}
						>{selfNode.id}</button
					>
					in the same graph — degree {selfDegree}, so the rule does not put it among these seven
				{:else}
					this widget is NOT declared in the graph artifact — the node it claims does not exist
				{/if}
			</p>
		</footer>
	</section>
{/if}

<style>
	.widget {
		width: 420px;
		padding: 10px 12px 8px;
		display: grid;
		gap: 6px;
		font-size: 12px;
		pointer-events: auto;
	}
	header {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.ttl {
		font-weight: 600;
	}
	.grow {
		flex: 1;
	}
	svg {
		width: 100%;
		height: 92px;
		display: block;
	}
	.node rect {
		fill: rgba(255, 255, 255, 0.06);
		stroke: var(--glass-brd);
	}
	.node text {
		fill: var(--fg);
		font-size: 11px;
		font-family: ui-monospace, monospace;
	}
	.node {
		cursor: pointer;
	}
	/* Motion means ORIENTATION or ATTENTION. This is orientation: the box the
	   pointer is on brightens so the click target is unambiguous. Nothing here
	   animates on its own. */
	.node:hover rect,
	.node:focus-visible rect {
		fill: rgba(255, 255, 255, 0.14);
		stroke: var(--accent);
	}
	footer p {
		margin: 0;
		color: var(--muted);
		font-size: 10.5px;
		line-height: 1.45;
	}
	.link {
		background: none;
		border: none;
		padding: 0;
		color: var(--accent);
		font: inherit;
		text-decoration: underline;
	}
</style>
