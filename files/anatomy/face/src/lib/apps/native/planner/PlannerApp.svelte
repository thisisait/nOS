<!--
  Planner — the roadmap DataTable as an interactive graph (face-planner).

  Slice 1 is READ-ONLY: it renders the roadmap rows as a Svelte Flow graph —
  nodes are rows (coloured by status), edges are parent→child, laid out one
  column per track. Pan/zoom/select; nothing writes yet. The editor slices add
  drag-to-reparent and write-back through the tables BFF (RBAC-gated), with the
  DataTable staying the source of truth and this graph a controlled projection.

  Svelte Flow (@xyflow/svelte, MIT) was chosen over the DIY-SVG GraphView
  because the planner's REASON to exist is interactive editing, which the
  read-only SVG cannot cheaply grow into (FOSS survey 2026-09-05). DataTables
  remain SoT: the shaping is a pure module ($lib/tables/planner.ts), this file
  is just the renderer + load.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { loadTable } from '$lib/api/tables';
	import { rowsToGraph } from '$lib/tables/planner';
	import { StatusNote, Badge } from '$lib/components/ui';

	// Row status → node colour. Unknown status falls to the neutral slab, never
	// crashes — a new status the table adds simply renders grey until named here.
	const STATUS_BG: Record<string, string> = {
		shipped: '#1f5c3a',
		active: '#1e4b78',
		next: '#6f5312',
		blocked: '#6e2532',
		queued: '#343a45',
		parked: '#343a45',
		dropped: '#26292f'
	};

	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let dangling = $state<string[]>([]);
	let phase = $state<'loading' | 'ok' | 'empty' | 'err'>('loading');
	let err = $state('');
	let source = $state<'keap' | 'fallback'>('keap');

	async function load() {
		phase = 'loading';
		try {
			const t = await loadTable('roadmap');
			source = t.source;
			const g = rowsToGraph(t);
			dangling = g.danglingParents;
			nodes = g.nodes.map((n) => ({
				id: n.id,
				position: n.position,
				data: { label: n.data.label },
				style: `background:${STATUS_BG[n.data.status] ?? '#343a45'};color:#e8ecf3;`
					+ 'border:1px solid var(--border,#333a45);border-radius:8px;'
					+ 'font-size:12px;padding:6px 10px;width:240px;'
					+ (n.data.orphanParent ? 'outline:1px dashed #b8863b;' : '')
			})) as Node[];
			edges = g.edges.map((e) => ({ id: e.id, source: e.source, target: e.target })) as Edge[];
			phase = nodes.length ? 'ok' : 'empty';
		} catch (e) {
			err = e instanceof Error ? e.message : String(e);
			phase = 'err';
		}
	}

	onMount(load);
</script>

<div class="planner">
	<header>
		<strong>Planner</strong>
		<span class="sub">roadmap · read-only</span>
		{#if source === 'fallback'}<Badge tone="warn">KEAP down — fallback</Badge>{/if}
		{#if dangling.length}<Badge tone="warn">{dangling.length} dangling parent{dangling.length > 1 ? 's' : ''}</Badge>{/if}
		<button class="refresh" onclick={load} aria-label="Reload the roadmap">↻</button>
	</header>

	{#if phase === 'loading'}
		<StatusNote kind="loading" title="Loading">Reading the roadmap DataTable…</StatusNote>
	{:else if phase === 'err'}
		<StatusNote kind="error" title="Could not read the roadmap">{err}</StatusNote>
	{:else if phase === 'empty'}
		<StatusNote kind="empty" title="No rows">The roadmap table is empty.</StatusNote>
	{:else}
		<div class="flow">
			<SvelteFlow
				bind:nodes
				bind:edges
				fitView
				nodesConnectable={false}
				elementsSelectable={true}
			>
				<Background />
				<Controls />
				<MiniMap pannable zoomable />
			</SvelteFlow>
		</div>
	{/if}
</div>

<style>
	.planner {
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
	.refresh {
		margin-left: auto;
		background: transparent;
		border: 1px solid var(--border, #333a45);
		color: var(--fg, #e8ecf3);
		border-radius: 6px;
		cursor: pointer;
		padding: 0.15rem 0.5rem;
	}
	.flow {
		flex: 1 1 auto;
		min-height: 0;
	}
	/* Svelte Flow needs a sized parent; the flex child gives it one. */
	.flow :global(.svelte-flow) {
		background: var(--bg, #14171c);
	}
</style>
