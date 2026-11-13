<!--
  Planner — the roadmap as a passive skill tree (face-skill-tree-view; operator
  2026-11-13, row roadmap-organic-structure).

  The core in the centre, the 13 apex organ systems as keystones on ring 1 (each in its
  own wedge), every row growing outward from its system. A node's colour is its state
  under the frontier rule of tools/roadmap-status.py (frontierStates in
  $lib/tables/planner.ts): shipped and active rows are the allocated tree, drawn as lit
  connectors from the core; a frontier row with a ready spec (the loop builds it) is filled
  and pulses, one that needs a spec first is hollow and still; a row under an ungrown
  ancestor is dim and its detail names the blocker. Milestones orbit the tree; rows that
  hang under no system form the dim halo outside it.

  Svelte Flow like the Roadmap graph, so drag-to-reparent is the same gesture over the
  same write: reparentPayload → tablesUpsertRow, gated by the BFF's canWrite. Rows are
  gems; a label shows by level of detail (systems always, epics at medium zoom, leaves
  up close) and on hover, focus and selection. Guides (wedges, rings, orbit) are one SVG
  behind the nodes; the level of detail is one class on the wrapper, so zooming costs no
  per-node work.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		SvelteFlow,
		Background,
		Controls,
		MiniMap,
		ViewportPortal,
		type Node,
		type Edge,
		type Viewport
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import './graph-theme.css';
	import { loadTable, tablesUpsertRow } from '$lib/api/tables';
	import { ApiError } from '$lib/api/client';
	import {
		frontierStates,
		skillTreeLayout,
		reparentPayload,
		ORGAN_RING,
		type TreeLayout,
		type TreeState,
		type TreeStateInfo
	} from '$lib/tables/planner';
	import type { DataTable } from '$lib/contracts';
	import { StatusNote, Badge } from '$lib/components/ui';
	import RowDetail from './RowDetail.svelte';
	import SkillNode from './SkillNode.svelte';

	const CORE = '__core__';
	const nodeTypes = { skill: SkillNode };
	const LEGEND: { state: TreeState; label: string; spec?: string }[] = [
		{ state: 'shipped', label: 'shipped' },
		{ state: 'allocated', label: 'active' },
		{ state: 'frontier', label: 'frontier, spec ready', spec: 'spec-ready' },
		{ state: 'frontier', label: 'frontier, needs a spec', spec: 'spec-needed' },
		{ state: 'doing', label: 'doing' },
		{ state: 'review', label: 'review' },
		{ state: 'blocked', label: 'blocked' },
		{ state: 'milestone', label: 'milestone' },
		{ state: 'ungrown', label: 'outside the ring' },
		{ state: 'dormant', label: 'queued / parked' }
	];
	/** Node box per rank (the layout gives centres; Svelte Flow positions a top-left corner). */
	const SIZE: Record<string, number> = { core: 56, system: 30, epic: 14, leaf: 10, halo: 8 };
	const LOD = { mid: 0.7, near: 1.4 }; // zoom at which epic, then leaf labels appear

	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let phase = $state<'loading' | 'ok' | 'empty' | 'err'>('loading');
	let err = $state('');
	let source = $state<'keap' | 'fallback'>('keap');
	let table = $state.raw<DataTable | null>(null);
	let states = $state.raw(new Map<string, TreeStateInfo>());
	let layout = $state.raw<TreeLayout | null>(null);
	let canWrite = $derived(table?.canWrite ?? false);
	let action = $state('');
	let hideDormant = $state(true); // queued/parked/dropped are a third of the board
	let selectedId = $state<string | null>(null);
	let zoom = $state(0.2);
	const lod = $derived(zoom >= LOD.near ? 'lod-near' : zoom >= LOD.mid ? 'lod-mid' : 'lod-far');
	/** System labels grow against the zoom (up to 1.8×) so the 13 names read at fitView, uncollided. */
	const lblScale = $derived(Math.min(1.8, Math.max(1, 1 / zoom)));
	const selectedRow = $derived(
		selectedId && table ? (table.rows.find((r) => r.id === selectedId) ?? null) : null
	);
	const selectedInfo = $derived(
		selectedRow ? states.get(String(selectedRow.slug ?? '')) : undefined
	);
	const count = (s: TreeState) => [...states.values()].filter((v) => v.state === s).length;
	const readyCount = $derived(
		[...states.values()].filter((v) => v.state === 'frontier' && v.ready).length
	);
	/** Buildable rows only: the loop builds a ready spec; a needs-spec row gets an explore draft first. */
	const specClass = (info: TreeStateInfo | undefined) =>
		info?.ready === undefined ? '' : info.ready ? ' spec-ready' : ' spec-needed';
	const tells = new Map(ORGAN_RING.map((r) => [r.key, r.tells]));

	function text(v: unknown): string {
		return v == null ? '' : String(v);
	}

	function rankOf(slug: string, info: TreeStateInfo | undefined, ring: Set<string>): string {
		if (ring.has(slug)) return 'system';
		if (!info || info.depth < 0) return info?.state === 'milestone' ? 'epic' : 'halo';
		return info.depth === 1 ? 'epic' : 'leaf';
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
			const rank = rankOf(slug, info, ring);
			const size = SIZE[rank];
			const tell = rank === 'system' ? tells.get(slug) : undefined;
			rowNodes.push({
				id: r.id,
				type: 'skill',
				position: { x: pos.x - size / 2, y: pos.y - size / 2 },
				width: size,
				height: size,
				data: { label, tells: tell },
				class: `skill rank-${rank} st-${state}${specClass(info)}`,
				ariaLabel: `${label} — ${state}${info?.ready === false ? ', needs a spec' : ''}${tell ? `. ${tell}` : ''}${info?.blockedBy ? `, blocked by ${info.blockedBy}` : ''}`,
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
				type: 'straight',
				class: s === 'shipped' || s === 'allocated' ? 'grown' : s === 'frontier' ? 'front' : '',
				deletable: source !== CORE
			});
		}
		const core: Node = {
			id: CORE,
			type: 'skill',
			position: { x: -SIZE.core / 2, y: -SIZE.core / 2 },
			width: SIZE.core,
			height: SIZE.core,
			data: { label: 'core' },
			class: 'skill rank-core st-shipped',
			ariaLabel: 'core — the shipped estate',
			draggable: false,
			selectable: false,
			connectable: false,
			deletable: false
		};
		states = st;
		layout = lay;
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

	const onmove = (_e: unknown, vp: Viewport) => (zoom = vp.zoom);

	/** Guide geometry: wedge paths and ring radii, from the layout (flow coordinates). */
	const guides = $derived.by(() => {
		if (!layout) return null;
		const R = Math.max(
			layout.rings[layout.rings.length - 1],
			layout.orbit,
			layout.halo[layout.halo.length - 1] ?? 0
		);
		const rim = layout.rings[layout.rings.length - 1] + 60;
		const hub = layout.rings[1] * 0.55;
		const pt = (r: number, a: number) =>
			`${(r * Math.cos(a)).toFixed(1)} ${(r * Math.sin(a)).toFixed(1)}`;
		const wedges = layout.sectors.map((s) => {
			const big = s.to - s.from > Math.PI ? 1 : 0;
			return `M ${pt(hub, s.from)} L ${pt(rim, s.from)} A ${rim} ${rim} 0 ${big} 1 ${pt(rim, s.to)} L ${pt(hub, s.to)} A ${hub} ${hub} 0 ${big} 0 ${pt(hub, s.from)} Z`;
		});
		return {
			R: R + 80,
			wedges,
			rings: layout.rings.slice(1),
			orbit: layout.orbit,
			halo: layout.halo
		};
	});

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
		{#if layout?.absent.length}<Badge tone="warn">ring incomplete: {layout.absent.join(', ')}</Badge
			>{/if}
		{#if action}<span class="action" class:err={action !== 'saving…'}>{action}</span>{/if}
		<span class="tally">
			<span>{count('frontier')} frontier ({readyCount} spec ready)</span>
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
		<div class="flow {lod}" style="--lbl-scale: {lblScale.toFixed(2)}">
			<SvelteFlow
				bind:nodes
				bind:edges
				{nodeTypes}
				fitView
				minZoom={0.05}
				maxZoom={4}
				onlyRenderVisibleElements
				nodesConnectable={canWrite}
				elementsSelectable={true}
				{onconnect}
				{ondelete}
				{onbeforedelete}
				{onmove}
				onmoveend={onmove}
				onselectionchange={({ nodes: sel }) => (selectedId = sel[0]?.id ?? null)}
			>
				<Background gap={40} size={1} />
				{#if guides}
					<ViewportPortal target="back">
						<svg
							class="guides"
							aria-hidden="true"
							width={guides.R * 2}
							height={guides.R * 2}
							viewBox="{-guides.R} {-guides.R} {guides.R * 2} {guides.R * 2}"
							style="left:{-guides.R}px; top:{-guides.R}px"
						>
							{#each guides.wedges as d, i (i)}
								<path {d} class="wedge" class:alt={i % 2 === 1} />
							{/each}
							{#each guides.rings as r (r)}
								<circle {r} class="ring" />
							{/each}
							{#if guides.orbit}<circle r={guides.orbit} class="orbit" />{/if}
							{#each guides.halo as r (r)}
								<circle {r} class="halo" />
							{/each}
							<circle r={guides.rings[0] * 0.55} class="hub" />
						</svg>
					</ViewportPortal>
				{/if}
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
						{#if selectedInfo.ready}
							<p class="spec">spec ready: the loop may build it</p>
						{:else if selectedInfo.ready === false}
							<p class="spec needs">
								needs a spec: no {selectedInfo.missing?.join(', no ')}. An explore draft comes
								first.
							</p>
						{/if}
						{#if selectedInfo.blockedBy}
							<p class="blocker">
								blocked by <code>{selectedInfo.blockedBy}</code> ({selectedInfo.blockedByStatus})
							</p>
						{/if}
					{/if}
				</RowDetail>
			{/if}

			<div class="legend" aria-label="Legend">
				<span class="chip"><i class="gem-sm hex"></i>organ system</span>
				<span class="chip"><i class="gem-sm epic"></i>epic</span>
				<span class="chip"><i class="gem-sm leaf"></i>row</span>
				<span class="chip"><i class="gem-sm stone"></i>milestone</span>
				<span class="sep" aria-hidden="true"></span>
				{#each LEGEND as l (l.label)}
					<span class="chip"><i class="dot st-{l.state} {l.spec ?? ''}"></i>{l.label}</span>
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
		background: radial-gradient(
			circle at 50% 45%,
			color-mix(in srgb, var(--ok) 7%, var(--bg)) 0,
			var(--bg) 55%
		);
	}
	.flow :global(.svelte-flow__background) {
		opacity: 0.35;
	}

	/* Guides: the systems' wedges, the rings, the milestone orbit and the halo — behind everything. */
	.guides {
		position: absolute;
		pointer-events: none;
	}
	.guides .wedge {
		fill: var(--fg);
		fill-opacity: 0.018;
		stroke: var(--glass-brd);
		stroke-width: 1;
	}
	.guides .wedge.alt {
		fill-opacity: 0.04;
	}
	.guides .ring,
	.guides .hub {
		fill: none;
		stroke: var(--glass-brd);
		stroke-width: 1;
	}
	.guides .hub {
		fill: color-mix(in srgb, var(--ok) 6%, transparent);
		stroke: color-mix(in srgb, var(--ok) 30%, transparent);
	}
	.guides .orbit {
		fill: none;
		stroke: var(--fg);
		stroke-opacity: 0.18;
		stroke-dasharray: 6 10;
	}
	.guides .halo {
		fill: none;
		stroke: var(--fg);
		stroke-opacity: 0.06;
		stroke-dasharray: 2 8;
	}

	/* ── Nodes. The box is the gem's size; the label hangs below it. State sets --node. ── */
	.flow :global(.svelte-flow__node.skill) {
		--node: var(--glass-brd);
		--node-core: color-mix(in srgb, var(--node) 30%, var(--bg));
		border-radius: 50%;
		background: transparent;
		border: 0;
		padding: 0;
		box-shadow: none;
		color: var(--fg);
		font-size: 11px;
	}
	.flow :global(.svelte-flow__node.skill:focus-visible) {
		outline: 2px solid var(--accent);
		outline-offset: 4px;
	}
	.flow :global(.svelte-flow__node.skill.selected .gem) {
		box-shadow:
			0 0 0 2px var(--bg),
			0 0 0 4px var(--accent);
	}

	/* Rank shapes: core disc, system keystone (hexagon), epic ring, leaf dot, halo mote. */
	.flow :global(.svelte-flow__node.rank-core .gem) {
		background: radial-gradient(circle, var(--ok) 0 30%, var(--node-core) 32% 100%);
		box-shadow:
			0 0 0 3px var(--ok),
			0 0 0 7px var(--bg),
			0 0 0 8px color-mix(in srgb, var(--ok) 50%, transparent),
			0 0 48px 16px var(--ok-soft);
	}
	.flow :global(.svelte-flow__node.rank-system .gem) {
		border-radius: 0;
		clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
		background: var(--node);
	}
	.flow :global(.svelte-flow__node.rank-system .gem::before) {
		content: '';
		position: absolute;
		inset: 3px;
		clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
		background: var(--node-core);
	}
	.flow :global(.svelte-flow__node.rank-system .gem::after) {
		content: '';
		position: absolute;
		inset: 10px;
		border-radius: 50%;
		background: var(--node);
	}
	.flow :global(.svelte-flow__node.rank-epic .gem) {
		background: var(--node-core);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.flow :global(.svelte-flow__node.rank-halo .gem) {
		opacity: 0.7;
	}

	/* States: the frontier rule's word for each row, design tokens only. */
	.flow :global(.svelte-flow__node.st-shipped) {
		--node: var(--ok);
	}
	.flow :global(.svelte-flow__node.st-allocated) {
		--node: var(--info);
	}
	.flow :global(.svelte-flow__node.st-frontier) {
		--node: var(--warn);
	}
	.flow :global(.svelte-flow__node.rank-leaf.st-frontier .gem),
	.flow :global(.svelte-flow__node.rank-halo.st-frontier .gem) {
		background: var(--node-core);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.flow :global(.svelte-flow__node.st-frontier::after) {
		content: '';
		position: absolute;
		inset: -3px;
		border-radius: 50%;
		border: 2px solid var(--warn);
		pointer-events: none;
		animation: pulse 2.4s ease-out infinite;
	}
	/* A ready spec is a filled, pulsing gem; a needs-spec row is hollow and still (not buildable yet). */
	.flow :global(.svelte-flow__node.st-frontier.spec-ready .gem) {
		background: var(--node);
	}
	.flow :global(.svelte-flow__node.st-frontier.spec-needed .gem) {
		background: var(--node-core);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.flow :global(.svelte-flow__node.st-frontier.spec-needed::after) {
		display: none;
	}
	@keyframes pulse {
		0% {
			transform: scale(0.9);
			opacity: 0.9;
		}
		100% {
			transform: scale(2.1);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.flow :global(.svelte-flow__node.st-frontier::after) {
			animation: none;
			transform: none;
			opacity: 0.55;
			box-shadow: 0 0 10px 3px var(--warn-soft);
		}
	}
	.flow :global(.svelte-flow__node.st-doing) {
		--node: var(--warn);
	}
	.flow :global(.svelte-flow__node.st-doing .gem) {
		background: radial-gradient(circle, var(--bg) 0 22%, var(--node) 26% 100%);
	}
	.flow :global(.svelte-flow__node.st-review) {
		--node: var(--info-ink);
	}
	.flow :global(.svelte-flow__node.st-review .gem) {
		background: var(--info-soft);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.flow :global(.svelte-flow__node.st-blocked) {
		--node: var(--muted);
		opacity: 0.35;
	}
	.flow :global(.svelte-flow__node.st-milestone) {
		--node: var(--fg);
	}
	.flow :global(.svelte-flow__node.st-milestone .gem) {
		border-radius: 2px;
		transform: rotate(45deg);
		background: var(--glass);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.flow :global(.svelte-flow__node.st-ungrown) {
		--node: var(--bad);
	}
	.flow :global(.svelte-flow__node.st-ungrown .gem) {
		background: var(--bad-soft);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.flow :global(.svelte-flow__node.st-dormant) {
		--node: var(--glass-brd);
		opacity: 0.55;
	}

	/* Level of detail: systems and the core always, epics from medium zoom, leaves up close;
	   hover, focus and selection always open a label. */
	.flow :global(.svelte-flow__node.rank-core .lbl),
	.flow :global(.svelte-flow__node.rank-system .lbl),
	.flow.lod-mid :global(.svelte-flow__node.rank-epic .lbl),
	.flow.lod-near :global(.svelte-flow__node.rank-epic .lbl),
	.flow.lod-near :global(.svelte-flow__node.rank-leaf .lbl),
	.flow.lod-near :global(.svelte-flow__node.rank-halo .lbl),
	.flow :global(.svelte-flow__node.skill:hover .lbl),
	.flow :global(.svelte-flow__node.skill:focus-visible .lbl),
	.flow :global(.svelte-flow__node.skill.selected .lbl) {
		display: flex;
	}
	.flow :global(.svelte-flow__node.rank-system .lbl) {
		font-size: 14px;
		font-weight: 600;
		top: calc(100% + 8px);
		background: color-mix(in srgb, var(--glass) 80%, var(--bg));
	}
	.flow :global(.svelte-flow__node.rank-core .lbl) {
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		top: calc(100% + 10px);
	}
	.flow :global(.svelte-flow__node.rank-epic .lbl) {
		font-size: 12px;
	}
	.flow :global(.svelte-flow__node.skill:hover),
	.flow :global(.svelte-flow__node.skill:focus-visible),
	.flow :global(.svelte-flow__node.skill.selected) {
		z-index: 20 !important;
	}
	.flow :global(.svelte-flow__node.skill:hover .lbl),
	.flow :global(.svelte-flow__node.skill:focus-visible .lbl),
	.flow :global(.svelte-flow__node.skill.selected .lbl) {
		max-width: 320px;
		white-space: normal;
		text-align: center;
	}
	.flow :global(.svelte-flow__node.skill:hover .tells),
	.flow :global(.svelte-flow__node.skill:focus-visible .tells),
	.flow :global(.svelte-flow__node.skill.selected .tells) {
		display: block;
	}
	.flow :global(.svelte-flow__node.skill .svelte-flow__handle) {
		opacity: 0;
		width: 6px;
		height: 6px;
		min-width: 0;
		min-height: 0;
	}
	.flow :global(.svelte-flow__node.skill:hover .svelte-flow__handle),
	.flow :global(.svelte-flow__node.skill.selected .svelte-flow__handle) {
		opacity: 1;
	}

	/* Connectors: allocated paths lit from the core outward; the frontier's own link dashed. */
	.flow :global(.svelte-flow__edge-path) {
		stroke: var(--glass-brd);
		stroke-width: 1;
	}
	.flow :global(.svelte-flow__edge.grown .svelte-flow__edge-path) {
		stroke: var(--ok);
		stroke-width: 2;
		stroke-opacity: 0.85;
	}
	.flow :global(.svelte-flow__edge.front .svelte-flow__edge-path) {
		stroke: var(--warn);
		stroke-width: 1.5;
		stroke-dasharray: 3 5;
		stroke-opacity: 0.8;
	}
	.flow :global(.svelte-flow__edge.selected .svelte-flow__edge-path) {
		stroke: var(--accent);
		stroke-width: 2.5;
	}

	.legend {
		position: absolute;
		left: 0.6rem;
		bottom: 0.6rem;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
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
	.sep {
		width: 1px;
		height: 0.9rem;
		background: var(--glass-brd);
	}
	.dot,
	.gem-sm {
		--node: var(--glass-brd);
		width: 10px;
		height: 10px;
		border-radius: 50%;
		display: inline-block;
		box-sizing: border-box;
		background: var(--node);
	}
	.dot.st-shipped {
		--node: var(--ok);
	}
	.dot.st-allocated {
		--node: var(--info);
	}
	.dot.st-frontier,
	.dot.st-doing {
		--node: var(--warn);
	}
	.dot.st-frontier {
		background: var(--warn-soft);
		box-shadow:
			inset 0 0 0 2px var(--node),
			0 0 6px 1px var(--warn);
	}
	.dot.st-frontier.spec-ready {
		background: var(--node);
	}
	.dot.st-frontier.spec-needed {
		background: transparent;
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.dot.st-review {
		--node: var(--info-ink);
		background: var(--info-soft);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.dot.st-blocked {
		--node: var(--muted);
		opacity: 0.4;
	}
	.dot.st-milestone {
		--node: var(--fg);
		border-radius: 2px;
		transform: rotate(45deg);
		background: var(--glass);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.dot.st-ungrown {
		--node: var(--bad);
		background: var(--bad-soft);
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.dot.st-dormant {
		opacity: 0.6;
	}
	.gem-sm.hex {
		--node: var(--fg);
		width: 12px;
		height: 12px;
		border-radius: 0;
		clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
	}
	.gem-sm.epic {
		--node: var(--fg);
		background: transparent;
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.gem-sm.leaf {
		--node: var(--fg);
		width: 7px;
		height: 7px;
	}
	.gem-sm.stone {
		--node: var(--fg);
		width: 8px;
		height: 8px;
		border-radius: 1px;
		transform: rotate(45deg);
		background: transparent;
		box-shadow: inset 0 0 0 2px var(--node);
	}
	.state,
	.blocker,
	.spec {
		margin: 0.4rem 0 0;
		color: var(--fg);
	}
	.blocker,
	.spec.needs {
		color: var(--muted);
	}
</style>
