<!--
  Loops view — the agentic loop's HARNESS as a graph (face-planner slice 3).

  READ-ONLY BY CONSTRUCTION, like Wing /loop-editor and the Anatomy GraphView:
  the loop's shape is doctrine declared in files/anatomy/bone/ledger.py, compiled
  by tools/loop-graph-gen.py into loop-graph.json (imported build-time here) and
  gated against the source (test_loop_graph_is_sound.py). An editor that wrote
  the harness would BE the `harness` proposal kind — which the loop refuses. So
  nothing here drags or writes; it shows what the loop MAY do, and what it won't.

  The RUN data (loop_proposals/judge_runs/verdicts, live in wing.db via
  GET /bff/loop) is a later overlay — this slice draws the fixed structure.
-->
<script lang="ts">
	import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import raw from '$lib/anatomy/loop-graph.json';
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

	const KIND_BG: Record<string, string> = {
		stage: '#1e4b78',
		role: '#1f5c3a',
		table: '#343a45',
		intent: '#5a4a1e',
		toggle: '#6e4a12',
		agent: '#4a2f6e',
		route: '#26292f'
	};

	// Edge style by relation — the flow spine reads bright + animated; the
	// quieter axes (writes / proposes / may-write) recede.
	const EDGE_STYLE: Record<string, string> = {
		flow: 'stroke:#7fd1a6;stroke-width:2;',
		acts: 'stroke:#8aa0b8;stroke-width:1.5;',
		writes: 'stroke:#8aa0b8;stroke-dasharray:5 4;',
		proposes: 'stroke:#6a6f78;stroke-width:1;',
		governs: 'stroke:#c9902f;stroke-dasharray:2 3;',
		'may-write': 'stroke:#9a7fb8;stroke-dasharray:1 4;'
	};

	function nodeStyle(n: LoopNode): string {
		let s = `background:${KIND_BG[n.kind] ?? '#343a45'};color:#e8ecf3;`
			+ 'border:1px solid var(--border,#333a45);border-radius:8px;'
			+ 'font-size:12px;padding:6px 10px;width:190px;text-align:center;';
		if (n.disabled) s += 'opacity:0.6;border-style:dashed;border-color:#b8863b;';
		if (n.out_of_loop) s += 'border-style:dotted;';
		if (n.kind === 'toggle' && n.enabled === false) s += 'border-color:#b8863b;';
		return s;
	}

	function nodeLabel(n: LoopNode): string {
		if (n.kind === 'intent' && n.disabled) return `${n.label} · refused`;
		if (n.kind === 'intent' && n.operator_required) return `${n.label} · operator`;
		if (n.kind === 'toggle') return `${n.label}: ${n.enabled === true ? 'on' : n.enabled === false ? 'off' : '—'}`;
		if (n.kind === 'stage' && n.out_of_loop) return `${n.label} (out of loop)`;
		return n.label;
	}

	const nodes = $state.raw<Node[]>(
		graph.nodes.map((n) => ({
			id: n.id,
			position: { x: n.x, y: n.y },
			data: { label: nodeLabel(n) },
			style: nodeStyle(n),
			connectable: false,
			draggable: false
		})) as Node[]
	);
	const edges = $state.raw<Edge[]>(
		graph.edges.map((e) => ({
			id: e.id,
			source: e.source,
			target: e.target,
			label: e.label,
			animated: e.kind === 'flow',
			style: EDGE_STYLE[e.kind] ?? ''
		})) as Edge[]
	);
</script>

<div class="loops">
	<header>
		<strong>Loops</strong>
		<span class="sub">the harness · read-only · from ledger.py</span>
		<Badge tone="neutral">verdict actor: {graph.engine_actor}</Badge>
	</header>

	<div class="flow">
		<SvelteFlow {nodes} {edges} fitView nodesConnectable={false} nodesDraggable={false}>
			<Background />
			<Controls showLock={false} />
			<MiniMap pannable zoomable />
		</SvelteFlow>
	</div>

	<StatusNote kind="unwired" title="What the loop refuses">
		<ul class="refusals">
			{#each graph.refusals as r}<li>{r}</li>{/each}
		</ul>
	</StatusNote>
</div>

<style>
	.loops {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}
	header {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--border, #2a2f38);
		flex: 0 0 auto;
	}
	.sub {
		color: var(--muted, #9aa4b2);
		font-size: 0.8rem;
	}
	.flow {
		flex: 1 1 auto;
		min-height: 0;
	}
	.flow :global(.svelte-flow) {
		background: var(--bg, #14171c);
	}
	.refusals {
		margin: 0.2rem 0 0;
		padding-left: 1.1rem;
		font-size: 0.82rem;
	}
	.refusals li {
		margin: 0.15rem 0;
	}
</style>
