<!--
  Planner — the roadmap as a passive skill tree (face-skill-tree-view; operator
  2026-11-13, row roadmap-organic-structure).

  The core in the centre, the 13 apex organ systems on ring 1, every row growing
  outward from its system. A node's colour is its state under the frontier rule of
  tools/roadmap-status.py (frontierStates in $lib/tables/planner.ts): shipped and
  active rows are the allocated tree, the frontier (buildable now) is lit, a row
  under an ungrown ancestor is dim and its detail names the blocker. Rows that hang
  under no system, and milestones, wait in a band under the tree.

  Svelte Flow like the Roadmap graph, so drag-to-reparent is the same gesture over
  the same write: reparentPayload → tablesUpsertRow, gated by the BFF's canWrite.
  Rows are dots; the label shows on hover, focus and selection.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import './graph-theme.css';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import {
		frontierStates,
		skillTreeLayout,
		reparentPayload,
		ORGAN_RING,
		type TreeState,
		type TreeStateInfo
	} from '$lib/tables/planner';
	import type { DataTable } from '$lib/contracts';
	import { StatusNote, Badge } from '$lib/components/ui';
	import RowDetail from './RowDetail.svelte';

	const CORE = '__core__';
	const LEGEND: { state: TreeState; label: string }[] = [
		{ state: 'shipped', label: 'shipped' },
		{ state: 'allocated', label: 'active' },
		{ state: 'frontier', label: 'frontier' },
		{ state: 'doing', label: 'doing' },
		{ state: 'review', label: 'review' },
		{ state: 'blocked', label: 'blocked' },
		{ state: 'milestone', label: 'milestone' },
		{ state: 'ungrown', label: 'outside the ring' },
		{ state: 'dormant', label: 'queued / parked' }
	];

	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let phase = $state<'loading' | 'ok' | 'empty' | 'err'>('loading');
	let err = $state('');
	let source = $state<'keap' | 'fallback'>('keap');
	let table = $state.raw<DataTable | null>(null);
	let states = $state.raw(new Map<string, TreeStateInfo>());
	let absent = $state<string[]>([]);
	let canWrite = $derived(table?.canWrite ?? false);
	let action = $state('');
	let hideDormant = $state(true); // queued/parked/dropped are a third of the board
	let selectedId = $state<string | null>(null);
	const selectedRow = $derived(
		selectedId && table ? (table.rows.find((r) => r.id === selectedId) ?? null) : null
	);
	const selectedInfo = $derived(
		selectedRow ? states.get(String(selectedRow.slug ?? '')) : undefined
	);
	const count = (s: TreeState) => [...states.values()].filter((v) => v.state === s).length;

	function text(v: unknown): string {
		return v == null ? '' : String(v);
	}

	/** Lay out the FULL board (positions do not jump when a filter changes); the
	 *  dormant toggle only hides nodes, and Svelte Flow hides their edges with them. */
	function applyTree(t: DataTable) {
		const st = frontierStates(t.rows);
		const lay = skillTreeLayout(t.rows);
		const ring = new Set(ORGAN_RING.map((r) => r.key));
		const stateOf = new Map<string, TreeState>();
		const rowNodes: Node[] = [];
		for (const r of t.rows) {
			const pos = lay.positions.get(r.id);
			if (!pos) continue;
			const slug = text(r.slug);
			const info = st.get(slug);
			const state = info?.state ?? 'dormant';
			stateOf.set(r.id, state);
			const label = text(r.title) || slug || r.id;
			rowNodes.push({
				id: r.id,
				position: pos,
				data: { label },
				class: `skill st-${state}${ring.has(slug) ? ' system' : ''}`,
				ariaLabel: `${label} — ${state}${info?.blockedBy ? `, blocked by ${info.blockedBy}` : ''}`,
				hidden: hideDormant && state === 'dormant' && !ring.has(slug)
			});
		}
		const bySlug = new Map(t.rows.map((r) => [text(r.slug), r.id]));
		const treeEdges: Edge[] = [];
		for (const r of t.rows) {
			const slug = text(r.slug);
			const parentId = bySlug.get(text(r.parent));
			const source = ring.has(slug) ? CORE : parentId;
			if (!source || !lay.positions.has(r.id)) continue;
			const s = stateOf.get(r.id);
			treeEdges.push({
				id: `${source}->${r.id}`,
				source,
				target: r.id,
				class: s === 'shipped' || s === 'allocated' ? 'grown' : '',
				deletable: source !== CORE
			});
		}
		const core: Node = {
			id: CORE,
			position: { x: 0, y: 0 },
			data: { label: 'core' },
			class: 'skill core',
			draggable: false,
			selectable: false,
			connectable: false,
			deletable: false
		};
		states = st;
		absent = lay.absent;
		nodes = [core, ...rowNodes];
		edges = treeEdges;
		phase = t.rows.length ? 'ok' : 'empty';
	}

	async function load() {
		phase = 'loading';
		try {
			const t = await loadTable('roadmap');
			source = t.source;
			table = t;
			applyTree(t);
		} catch (e) {
			err = e instanceof Error ? e.message : String(e);
			phase = 'err';
		}
	}

	/** The Roadmap graph's write, unchanged: refused in the pure helper on a cycle or
	 *  self-parent, a minimal {slug, parent} merge through the tables BFF, reload after. */
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

	function onconnect(conn: { source: string; target: string }) {
		if (conn.source === CORE || conn.target === CORE) return; // the core is not a row
		void reparent(conn.target, conn.source);
	}

	/** Only an edge (one parent link) is ever deleted, and only by a writer: deleting a node takes
	 *  every edge touching it, so one Backspace un-parented a row and all its children (review 13e). */
	async function onbeforedelete({
		nodes: n
	}: {
		nodes: unknown[];
		edges: Edge[];
	}): Promise<boolean> {
		return canWrite && n.length === 0;
	}

	function ondelete(deleted: { edges?: Edge[] }) {
		if (!canWrite) return;
		for (const e of deleted.edges ?? []) if (e.source !== CORE) void reparent(e.target, null);
	}

	onMount(load);
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && selectedId) selectedId = null;
	}}
/>

<div class="tree">
	<header>
		<strong>Skill tree</strong>
		<span class="sub">{canWrite ? 'drag a handle to re-hang a row' : 'read-only'}</span>
		{#if source === 'fallback'}<Badge tone="warn">KEAP down — fallback</Badge>{/if}
		{#if absent.length}<Badge tone="warn">ring incomplete: {absent.join(', ')}</Badge>{/if}
		{#if action}<span class="action" class:err={action !== 'saving…'}>{action}</span>{/if}
		<span class="tally">
			<span>{count('frontier')} frontier</span>
			<span>{count('blocked')} blocked</span>
			<span>{count('ungrown')} outside the ring</span>
			<label class="chk"
				><input
					type="checkbox"
					bind:checked={hideDormant}
					onchange={() => table && applyTree(table)}
				/> hide queued</label
			>
		</span>
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
				minZoom={0.05}
				nodesConnectable={canWrite}
				elementsSelectable={true}
				{onconnect}
				{ondelete}
				{onbeforedelete}
				onselectionchange={({ nodes: sel }) => (selectedId = sel[0]?.id ?? null)}
			>
				<Background />
				<Controls />
				<MiniMap pannable zoomable />
			</SvelteFlow>

			{#if selectedRow}
				<RowDetail row={selectedRow} onclose={() => (selectedId = null)}>
					{#if selectedInfo}
						<p class="state">
							<i class="dot st-{selectedInfo.state}"></i>{selectedInfo.state}
							{#if selectedInfo.system}· {selectedInfo.system}, ring {selectedInfo.depth + 1}{/if}
						</p>
						{#if selectedInfo.blockedBy}
							<p class="blocker">
								blocked by <code>{selectedInfo.blockedBy}</code> ({selectedInfo.blockedByStatus})
							</p>
						{/if}
					{/if}
				</RowDetail>
			{/if}

			<div class="legend" aria-label="State legend">
				{#each LEGEND as l}
					<span class="chip"><i class="dot st-{l.state}"></i>{l.label}</span>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	.tree {
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
		border-bottom: 1px solid var(--glass-brd);
		flex: 0 0 auto;
	}
	.sub,
	.action,
	.tally {
		color: var(--muted);
		font-size: 0.8rem;
	}
	.action.err {
		color: var(--bad-ink);
	}
	.tally {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.chk {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		white-space: nowrap;
	}
	.refresh {
		background: transparent;
		border: 1px solid var(--glass-brd);
		color: var(--fg);
		border-radius: 6px;
		cursor: pointer;
		padding: 0.15rem 0.5rem;
	}
	.flow {
		flex: 1 1 auto;
		min-height: 0;
		position: relative;
	}
	.flow :global(.svelte-flow) {
		background: var(--bg);
	}

	/* A row is a dot; its label opens on hover, focus and selection. */
	.flow :global(.svelte-flow__node.skill) {
		width: 16px;
		height: 16px;
		min-width: 0;
		padding: 0;
		border-radius: 50%;
		border: 2px solid var(--glass-brd);
		background: var(--glass);
		color: var(--fg);
		font-size: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		box-shadow: none;
	}
	.flow :global(.svelte-flow__node.skill:hover),
	.flow :global(.svelte-flow__node.skill:focus-visible),
	.flow :global(.svelte-flow__node.skill.selected),
	.flow :global(.svelte-flow__node.skill.system),
	.flow :global(.svelte-flow__node.skill.core) {
		width: auto;
		height: auto;
		max-width: 220px;
		padding: 2px 10px;
		border-radius: 999px;
		font-size: 11px;
		z-index: 10;
	}
	.flow :global(.svelte-flow__node.skill.system) {
		font-size: 13px;
		font-weight: 600;
	}
	.flow :global(.svelte-flow__node.skill.core) {
		font-size: 14px;
		font-weight: 700;
		border-color: var(--ok);
		background: var(--ok-soft);
	}
	.flow :global(.svelte-flow__node.skill .svelte-flow__handle) {
		opacity: 0;
	}
	.flow :global(.svelte-flow__node.skill:hover .svelte-flow__handle),
	.flow :global(.svelte-flow__node.skill.selected .svelte-flow__handle) {
		opacity: 1;
	}
	.flow :global(.svelte-flow__edge-path) {
		stroke: var(--glass-brd);
	}
	.flow :global(.svelte-flow__edge.grown .svelte-flow__edge-path) {
		stroke: var(--ok);
		stroke-opacity: 0.6;
	}

	/* State: the frontier rule's word for each row, design tokens only. */
	.flow :global(.svelte-flow__node.st-shipped),
	.dot.st-shipped {
		background: var(--ok);
		border-color: var(--ok);
	}
	.flow :global(.svelte-flow__node.st-shipped) {
		color: var(--bg);
	}
	.flow :global(.svelte-flow__node.st-allocated),
	.dot.st-allocated {
		background: var(--info);
		border-color: var(--info);
	}
	.flow :global(.svelte-flow__node.st-allocated) {
		color: var(--bg);
	}
	.flow :global(.svelte-flow__node.st-frontier),
	.dot.st-frontier {
		background: var(--warn-soft);
		border-color: var(--warn);
		box-shadow: 0 0 10px 2px var(--warn);
	}
	.flow :global(.svelte-flow__node.st-doing),
	.dot.st-doing {
		background: var(--warn);
		border-color: var(--warn);
	}
	.flow :global(.svelte-flow__node.st-doing) {
		color: var(--bg);
	}
	.flow :global(.svelte-flow__node.st-review),
	.dot.st-review {
		background: var(--info-soft);
		border-color: var(--info-ink);
	}
	.flow :global(.svelte-flow__node.st-blocked),
	.dot.st-blocked {
		background: transparent;
		border-color: var(--muted);
		opacity: 0.4;
	}
	.flow :global(.svelte-flow__node.st-milestone),
	.dot.st-milestone {
		border-radius: 3px;
		background: var(--glass);
		border-color: var(--fg);
	}
	.flow :global(.svelte-flow__node.st-ungrown),
	.dot.st-ungrown {
		background: var(--bad-soft);
		border-color: var(--bad-ink);
	}
	.flow :global(.svelte-flow__node.st-dormant),
	.dot.st-dormant {
		background: var(--glass);
		border-color: var(--glass-brd);
		opacity: 0.6;
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
		background: var(--glass);
		border: 1px solid var(--glass-brd);
		border-radius: 8px;
		font-size: 0.72rem;
		z-index: 4;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--muted);
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		border: 2px solid var(--glass-brd);
		display: inline-block;
		box-sizing: border-box;
		margin-right: 0.3rem;
	}
	.state,
	.blocker {
		margin: 0.4rem 0 0;
		color: var(--fg);
	}
	.blocker {
		color: var(--muted);
	}
</style>
