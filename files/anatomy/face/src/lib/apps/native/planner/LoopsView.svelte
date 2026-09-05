<!--
  Loops view — the agentic loop's HARNESS as a graph (face-planner slice 3),
  with a LIVE-RUN OVERLAY (slice 4).

  READ-ONLY BY CONSTRUCTION, like Wing /loop-editor and the Anatomy GraphView:
  the loop's shape is doctrine declared in files/anatomy/bone/ledger.py, compiled
  by tools/loop-graph-gen.py into loop-graph.json (imported build-time) and gated
  against the source. An editor that wrote the harness would BE the `harness`
  proposal kind — refused. So nothing here drags or writes; the one live call is
  the read GET /bff/loop.

  Slice 4: the fixed structure is annotated with LIVE counts from wing.db (via
  GET /bff/loop — the same read RunsView uses): how many proposals/judge-runs/
  verdicts, which intents were actually exercised, and the pass/fail tally. The
  structure is what the loop MAY do; the overlay is what it HAS done.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import raw from '$lib/anatomy/loop-graph.json';
	import { loadLoop, type LoopResponse } from '$lib/api/loop';
	import { StatusNote, Badge } from '$lib/components/ui';

	type LoopNode = {
		id: string;
		kind: string;
		label: string;
		x: number;
		y: number;
		disabled?: boolean;
		operator_required?: boolean;
		out_of_loop?: boolean;
		enabled?: boolean | null;
	};
	type LoopEdge = { id: string; source: string; target: string; kind: string; label?: string };
	const graph = raw as { nodes: LoopNode[]; edges: LoopEdge[]; refusals: string[]; engine_actor: string };

	let live = $state<LoopResponse | null>(null);
	let loadErr = $state('');
	let loading = $state(true);

	async function load() {
		loading = true;
		try {
			live = await loadLoop();
			loadErr = live.error ?? '';
		} catch (e) {
			loadErr = e instanceof Error ? e.message : String(e);
			live = null;
		} finally {
			loading = false;
		}
	}
	onMount(load);

	// Proposals per intent_class, and the verdict tally — derived from the live
	// snapshot, empty when unconfigured/unloaded.
	const byIntent = $derived.by(() => {
		const m = new Map<string, number>();
		for (const p of live?.proposals ?? []) m.set(p.intent_class, (m.get(p.intent_class) ?? 0) + 1);
		return m;
	});
	const tally = $derived.by(() => {
		const t = { pass: 0, fail: 0, indeterminate: 0 } as Record<string, number>;
		for (const v of live?.verdicts ?? []) if (v.result in t) t[v.result]++;
		return t;
	});
	const configured = $derived(live?.configured === true);

	/** Live count for a node, or null when the overlay has nothing to say. */
	function countFor(id: string): number | null {
		if (!configured || !live) return null;
		const c = live.counts;
		switch (id) {
			case 'stage:propose':
			case 'table:loop_proposals':
				return c?.proposals ?? 0;
			case 'stage:judge':
			case 'table:loop_judge_runs':
				return c?.judgeRuns ?? 0;
			case 'stage:apply':
			case 'table:loop_verdicts':
				return c?.verdicts ?? 0;
		}
		if (id.startsWith('intent:')) return byIntent.get(id.slice('intent:'.length)) ?? 0;
		return null;
	}

	const KIND_BG: Record<string, string> = {
		stage: '#1e4b78', role: '#1f5c3a', table: '#343a45',
		intent: '#5a4a1e', toggle: '#6e4a12', agent: '#4a2f6e', route: '#26292f'
	};
	const EDGE_STYLE: Record<string, string> = {
		flow: 'stroke:#7fd1a6;stroke-width:2;',
		acts: 'stroke:#8aa0b8;stroke-width:1.5;',
		writes: 'stroke:#8aa0b8;stroke-dasharray:5 4;',
		proposes: 'stroke:#6a6f78;stroke-width:1;',
		governs: 'stroke:#c9902f;stroke-dasharray:2 3;',
		'may-write': 'stroke:#9a7fb8;stroke-dasharray:1 4;'
	};

	function nodeStyle(n: LoopNode, count: number | null): string {
		let s = `background:${KIND_BG[n.kind] ?? '#343a45'};color:#e8ecf3;`
			+ 'border:1px solid var(--border,#333a45);border-radius:8px;'
			+ 'font-size:12px;padding:6px 10px;width:190px;text-align:center;';
		if (n.disabled) s += 'opacity:0.6;border-style:dashed;border-color:#b8863b;';
		if (n.out_of_loop) s += 'border-style:dotted;';
		if (n.kind === 'toggle' && n.enabled === false) s += 'border-color:#b8863b;';
		// Exercised nodes (live count > 0) get a brighter edge — what has run.
		if (count && count > 0) s += 'box-shadow:0 0 0 2px #7fd1a6 inset;';
		return s;
	}

	function baseLabel(n: LoopNode): string {
		if (n.kind === 'intent' && n.disabled) return `${n.label} · refused`;
		if (n.kind === 'intent' && n.operator_required) return `${n.label} · operator`;
		if (n.kind === 'toggle') return `${n.label}: ${n.enabled === true ? 'on' : n.enabled === false ? 'off' : '—'}`;
		if (n.kind === 'stage' && n.out_of_loop) return `${n.label} (out of loop)`;
		return n.label;
	}

	const nodes = $derived.by<Node[]>(() =>
		graph.nodes.map((n) => {
			const c = countFor(n.id);
			const label = c != null && c > 0 ? `${baseLabel(n)}  ·  ${c}` : baseLabel(n);
			return {
				id: n.id,
				position: { x: n.x, y: n.y },
				data: { label },
				style: nodeStyle(n, c),
				connectable: false,
				draggable: false
			} as Node;
		})
	);
	const edges: Edge[] = graph.edges.map((e) => ({
		id: e.id, source: e.source, target: e.target, label: e.label,
		animated: e.kind === 'flow', style: EDGE_STYLE[e.kind] ?? ''
	})) as Edge[];
</script>

<div class="loops">
	<header>
		<strong>Loops</strong>
		<span class="sub">the harness · read-only · from ledger.py</span>
		{#if loading}
			<span class="sub">loading runs…</span>
		{:else if configured}
			<Badge tone="ok">✓ {tally.pass}</Badge>
			{#if tally.fail}<Badge tone="bad">✗ {tally.fail}</Badge>{/if}
			{#if tally.indeterminate}<Badge tone="warn">? {tally.indeterminate}</Badge>{/if}
			<span class="sub">{live?.counts?.proposals ?? 0} proposals · {live?.counts?.judgeRuns ?? 0} runs</span>
		{:else}
			<Badge tone="neutral">no live runs</Badge>
		{/if}
		<button class="refresh" onclick={load} aria-label="Reload loop runs">↻</button>
	</header>

	<div class="flow">
		<SvelteFlow {nodes} {edges} fitView nodesConnectable={false} nodesDraggable={false}>
			<Background />
			<Controls showLock={false} />
			<MiniMap pannable zoomable />
		</SvelteFlow>
	</div>

	{#if loadErr}
		<StatusNote kind="error" title="Loop runs unavailable">{loadErr}</StatusNote>
	{/if}
	<StatusNote kind="unwired" title="What the loop refuses">
		<ul class="refusals">
			{#each graph.refusals as r}<li>{r}</li>{/each}
		</ul>
	</StatusNote>
</div>

<style>
	.loops { display: flex; flex-direction: column; height: 100%; min-height: 0; }
	header {
		display: flex; align-items: center; gap: 0.6rem;
		padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border, #2a2f38); flex: 0 0 auto;
	}
	.sub { color: var(--muted, #9aa4b2); font-size: 0.8rem; }
	.refresh {
		margin-left: auto; background: transparent; border: 1px solid var(--border, #333a45);
		color: var(--fg, #e8ecf3); border-radius: 6px; cursor: pointer; padding: 0.15rem 0.5rem;
	}
	.flow { flex: 1 1 auto; min-height: 0; }
	.flow :global(.svelte-flow) { background: var(--bg, #14171c); }
	.refusals { margin: 0.2rem 0 0; padding-left: 1.1rem; font-size: 0.82rem; }
	.refusals li { margin: 0.15rem 0; }
</style>
