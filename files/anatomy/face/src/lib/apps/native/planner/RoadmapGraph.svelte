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
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import { rowsToGraph, reparentPayload } from '$lib/tables/planner';
	import type { DataTable } from '$lib/contracts';
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
	// The status legend, in board order — the fill colours above, given names.
	const STATUS_LEGEND: { key: string; label: string }[] = [
		{ key: 'active', label: 'active' },
		{ key: 'next', label: 'next' },
		{ key: 'queued', label: 'queued' },
		{ key: 'blocked', label: 'blocked' },
		{ key: 'shipped', label: 'shipped' },
		{ key: 'parked', label: 'parked' },
		{ key: 'dropped', label: 'dropped' }
	];
	// `kind` (a real roadmap column) as a left-border accent — a second glance
	// dimension beside the status fill: an epic reads differently from a fee.
	const KIND_ACCENT: Record<string, string> = {
		release: '#c9902f',
		epic: '#8a6fd8',
		feature: '#4a9db8',
		task: '#5a6472',
		fee: '#c26b6b',
		weakness: '#b8863b',
		decision: '#6a9a6a'
	};

	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let dangling = $state<string[]>([]);
	let phase = $state<'loading' | 'ok' | 'empty' | 'err'>('loading');
	let err = $state('');
	let source = $state<'keap' | 'fallback'>('keap');
	let table = $state.raw<DataTable | null>(null);
	/** Slice 2: interactive reparent writes back through the tables BFF, which
	 *  enforces manager-tier RBAC + holds the RW token. A non-manager gets
	 *  canWrite=false and the graph stays read-only (no dragging edges). */
	let canWrite = $derived(table?.canWrite ?? false);
	/** Transient edit status: '' idle, 'saving', or an error message. */
	let action = $state('');

	/** Detail panel: the id of the selected node, and the row it maps to. A
	 *  selection is READ-ONLY inspection — it never writes; reparent is the drag
	 *  gesture, not a click. */
	let selectedId = $state<string | null>(null);
	const selectedRow = $derived(
		selectedId && table ? (table.rows.find((r) => r.id === selectedId) ?? null) : null
	);

	// The row fields worth showing, in a sensible reading order; only the ones
	// with a value render (a roadmap row fills a handful, not all 20 columns).
	const FIELDS: { key: string; label: string }[] = [
		{ key: 'status', label: 'Status' },
		{ key: 'kind', label: 'Kind' },
		{ key: 'track', label: 'Track' },
		{ key: 'severity', label: 'Severity' },
		{ key: 'effort', label: 'Effort' },
		{ key: 'owner', label: 'Owner' },
		{ key: 'parent', label: 'Parent' },
		{ key: 'target', label: 'Target' },
		{ key: 'occurred_at', label: 'Landed' },
		{ key: 'verified', label: 'Verified' },
		{ key: 'verified_by', label: 'Verified by' },
		{ key: 'source', label: 'Source' },
		{ key: 'release', label: 'Release' }
	];
	function cellOf(row: DataTable['rows'][number], key: string): string {
		const v = row[key];
		return v == null ? '' : String(v);
	}

	async function load() {
		phase = 'loading';
		try {
			const t = await loadTable('roadmap');
			source = t.source;
			table = t;
			const g = rowsToGraph(t);
			dangling = g.danglingParents;
			nodes = g.nodes.map((n) => ({
				id: n.id,
				position: n.position,
				data: { label: n.data.label },
				style:
					`background:${STATUS_BG[n.data.status] ?? '#343a45'};color:#e8ecf3;` +
					'border:1px solid var(--border,#333a45);border-radius:8px;' +
					`border-left:5px solid ${KIND_ACCENT[n.data.kind] ?? '#343a45'};` +
					'font-size:12px;padding:6px 10px;width:240px;' +
					(n.data.orphanParent ? 'outline:1px dashed #b8863b;' : '')
			})) as Node[];
			edges = g.edges.map((e) => ({ id: e.id, source: e.source, target: e.target })) as Edge[];
			phase = nodes.length ? 'ok' : 'empty';
		} catch (e) {
			err = e instanceof Error ? e.message : String(e);
			phase = 'err';
		}
	}

	/** Reparent childId under parentId (null = un-parent). Cycle/self are refused
	 *  in the pure helper BEFORE any write; the write is a minimal merge so
	 *  status/verified (table-owned) are untouched. Reload from SoT after. */
	async function reparent(childId: string, parentId: string | null) {
		if (!table || !canWrite) return;
		action = 'saving…';
		try {
			const payload = reparentPayload(table, childId, parentId);
			await tablesUpsertRow('roadmap', payload as unknown as Record<string, unknown>);
			await load();
			action = '';
		} catch (e) {
			action = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'write failed';
		}
	}

	// Drag from a node's handle to another node = "make source the parent of
	// target" (source→target is a parent→child edge, matching the render).
	function onconnect(conn: { source: string; target: string }) {
		void reparent(conn.target, conn.source);
	}

	// Deleting an edge un-parents its child (target → root). Svelte Flow has
	// already dropped the edge from its state; the reload re-derives the truth.
	function ondelete(deleted: { edges?: Edge[] }) {
		if (!canWrite) return;
		for (const e of deleted.edges ?? []) void reparent(e.target, null);
	}

	onMount(load);
</script>

<div class="planner">
	<header>
		<strong>Planner</strong>
		<span class="sub">roadmap · {canWrite ? 'drag a handle to reparent' : 'read-only'}</span>
		{#if source === 'fallback'}<Badge tone="warn">KEAP down — fallback</Badge>{/if}
		{#if dangling.length}<Badge tone="warn"
				>{dangling.length} dangling parent{dangling.length > 1 ? 's' : ''}</Badge
			>{/if}
		{#if action}<span class="action" class:err={action !== 'saving…'}>{action}</span>{/if}
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
				nodesConnectable={canWrite}
				elementsSelectable={true}
				{onconnect}
				{ondelete}
				onselectionchange={({ nodes: sel }) => (selectedId = sel[0]?.id ?? null)}
			>
				<Background />
				<Controls />
				<MiniMap pannable zoomable />
			</SvelteFlow>

			{#if selectedRow}
				<aside class="detail" aria-label="Row detail">
					<div class="detail-head">
						<strong>{cellOf(selectedRow, 'title') || cellOf(selectedRow, 'slug')}</strong>
						<button class="close" onclick={() => (selectedId = null)} aria-label="Close detail"
							>×</button
						>
					</div>
					<code class="slug">{cellOf(selectedRow, 'slug')}</code>
					<dl>
						{#each FIELDS as f}
							{#if cellOf(selectedRow, f.key)}
								<dt>{f.label}</dt>
								<dd>{cellOf(selectedRow, f.key)}</dd>
							{/if}
						{/each}
					</dl>
					{#if cellOf(selectedRow, 'body')}
						<p class="body">{cellOf(selectedRow, 'body')}</p>
					{/if}
				</aside>
			{/if}

			<div class="legend" aria-label="Status legend">
				{#each STATUS_LEGEND as s}
					<span class="chip"><i style="background:{STATUS_BG[s.key]}"></i>{s.label}</span>
				{/each}
				<span class="chip note">border = kind</span>
			</div>
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
	.action {
		font-size: 0.8rem;
		color: var(--muted, #9aa4b2);
	}
	.action.err {
		color: var(--bad, #d98a94);
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
		position: relative; /* anchor for the detail overlay */
	}
	/* Svelte Flow needs a sized parent; the flex child gives it one. */
	.flow :global(.svelte-flow) {
		background: var(--bg, #14171c);
	}
	.legend {
		position: absolute;
		left: 0.6rem;
		bottom: 0.6rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem 0.6rem;
		max-width: 60%;
		padding: 0.35rem 0.5rem;
		background: color-mix(in srgb, var(--panel, #1b1f27) 88%, transparent);
		border: 1px solid var(--border, #333a45);
		border-radius: 8px;
		font-size: 0.72rem;
		z-index: 4;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		color: var(--muted, #9aa4b2);
	}
	.chip i {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		display: inline-block;
	}
	.chip.note {
		font-style: italic;
	}
	.detail {
		position: absolute;
		top: 0.6rem;
		right: 0.6rem;
		width: 260px;
		max-height: calc(100% - 1.2rem);
		overflow-y: auto;
		background: var(--panel, #1b1f27);
		border: 1px solid var(--border, #333a45);
		border-radius: 8px;
		padding: 0.6rem 0.75rem;
		font-size: 0.82rem;
		z-index: 5;
	}
	.detail-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}
	.detail-head strong {
		flex: 1 1 auto;
	}
	.close {
		background: transparent;
		border: none;
		color: var(--muted, #9aa4b2);
		font-size: 1.1rem;
		line-height: 1;
		cursor: pointer;
	}
	.slug {
		color: var(--muted, #9aa4b2);
		font-size: 0.75rem;
	}
	.detail dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.15rem 0.6rem;
		margin: 0.5rem 0 0;
	}
	.detail dt {
		color: var(--muted, #9aa4b2);
	}
	.detail dd {
		margin: 0;
		word-break: break-word;
	}
	.detail .body {
		margin: 0.6rem 0 0;
		padding-top: 0.5rem;
		border-top: 1px solid var(--border, #2a2f38);
		color: var(--fg, #e8ecf3);
		white-space: pre-wrap;
	}
</style>
