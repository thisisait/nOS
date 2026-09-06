<!--
  Routing view — the agent CAPABILITY space as a graph (dtt-routing-address).

  READ-ONLY BY CONSTRUCTION, like the Loops view: the capability side is
  git-derived doctrine (agent manifests → tools/agent-capability.py →
  tools/routing-graph-gen.py → routing-graph.json, imported build-time and gated
  against a fresh generate). Nothing here drags or writes.

  What it shows: each agent under its execution locus (WHERE), wired to the
  task_types it may do (CO, "can do") and the scopes it touches (KAM). What it
  does NOT show yet: the LIVE match of assignments to capabilities — those are
  runtime currentState rows, and the matcher (assignment ⊆ capability) is
  defined once in tools/nos_work_uri.py; the terminal reader
  tools/work-assignment.py prints the live match until a BFF hop carries the
  reference matcher's own output into the face (kept out to avoid forking the law).
-->
<script lang="ts">
	import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import raw from '$lib/anatomy/routing-graph.json';
	import { StatusNote } from '$lib/components/ui';

	type RNode = { id: string; kind: string; label: string; x: number; y: number; address?: string };
	type REdge = { source: string; target: string; kind: string };
	const graph = raw as {
		nodes: RNode[];
		edges: REdge[];
		agents: string[];
		task_types: string[];
		scopes: string[];
		wheres: string[];
	};

	const KIND_BG: Record<string, string> = {
		where: '#1e4b78',
		agent: '#4a2f6e',
		task_type: '#1f5c3a',
		scope: '#6e4a12'
	};
	const EDGE_STYLE: Record<string, string> = {
		'runs-in': 'stroke:#8aa0b8;stroke-width:1.5;',
		'can-do': 'stroke:#7fd1a6;stroke-width:1.5;',
		touches: 'stroke:#c9902f;stroke-dasharray:4 3;'
	};

	function nodeStyle(kind: string): string {
		return (
			`background:${KIND_BG[kind] ?? '#343a45'};color:#e8ecf3;` +
			'border:1px solid var(--border,#333a45);border-radius:8px;' +
			`font-size:12px;padding:5px 9px;width:${kind === 'agent' ? 190 : 150}px;text-align:center;`
		);
	}

	const nodes: Node[] = graph.nodes.map((n) => ({
		id: n.id,
		position: { x: n.x, y: n.y },
		data: { label: n.kind === 'where' ? `▸ ${n.label}` : n.label },
		style: nodeStyle(n.kind),
		connectable: false,
		draggable: false
	})) as Node[];
	const edges: Edge[] = graph.edges.map((e) => ({
		id: `${e.source}->${e.target}:${e.kind}`,
		source: e.source,
		target: e.target,
		style: EDGE_STYLE[e.kind] ?? '',
		animated: e.kind === 'can-do'
	})) as Edge[];

	const KIND_LEGEND: { key: string; label: string }[] = [
		{ key: 'where', label: 'locus' },
		{ key: 'agent', label: 'agent' },
		{ key: 'task_type', label: 'task type' },
		{ key: 'scope', label: 'scope' }
	];
</script>

<div class="routing">
	<header>
		<strong>Routing</strong>
		<span class="sub"
			>capability space · read-only · {graph.agents.length} agents · from agent manifests</span
		>
		<span class="legend">
			{#each KIND_LEGEND as k}
				<span class="chip"><i style="background:{KIND_BG[k.key]}"></i>{k.label}</span>
			{/each}
		</span>
	</header>

	<div class="flow">
		<SvelteFlow {nodes} {edges} fitView nodesConnectable={false} nodesDraggable={false}>
			<Background />
			<Controls showLock={false} />
			<MiniMap pannable zoomable />
		</SvelteFlow>
	</div>

	<StatusNote kind="unwired" title="The live match is not here (by design)">
		This is the capability SPACE — who may do what, where, touching what. The live match of runtime
		assignments (currentState rows) to these capabilities is
		<code>assignment ⊆ capability</code>, defined once in <code>tools/nos_work_uri.py</code> and
		printed by <code>tools/work-assignment.py</code>; it stays there until a BFF hop can carry the
		reference matcher's own output into the face, rather than forking the rule.
	</StatusNote>
</div>

<style>
	.routing {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}
	header {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--border, #2a2f38);
		flex: 0 0 auto;
	}
	.sub {
		color: var(--muted, #9aa4b2);
		font-size: 0.8rem;
	}
	.legend {
		display: flex;
		gap: 0.6rem;
		margin-left: auto;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		color: var(--muted, #9aa4b2);
		font-size: 0.72rem;
	}
	.chip i {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		display: inline-block;
	}
	.flow {
		flex: 1 1 auto;
		min-height: 0;
	}
	.flow :global(.svelte-flow) {
		background: var(--bg, #14171c);
	}
	code {
		font-size: 0.82em;
		background: var(--panel, #1b1f27);
		padding: 0 0.25em;
		border-radius: 3px;
	}
</style>
