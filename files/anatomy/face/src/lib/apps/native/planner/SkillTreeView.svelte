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
  gems; names live in ONE screen-space label layer over the flow, placed by labelPlan: a
  constant font size whatever the zoom, one line each, and a greedy collision pass by
  priority (sector name > system > epic > frontier > leaf) so no label ever lies on another
  (the operator's finding 11-13). A system reads by its apex name; each sector's name also
  stands at the rim of its wedge, the way PoE names a class at the edge of the tree. Hover,
  focus and selection pin a label; the full title is the gem's tooltip and the detail panel.
  Guides (wedges, rings, orbit) are one SVG behind the nodes.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		SvelteFlow,
		Background,
		Controls,
		MiniMap,
		ViewportPortal,
		ConnectionMode,
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
		skillTreeLabels,
		labelPlan,
		labelBox,
		gemRank,
		reparentPayload,
		GEM_SIZE,
		ORGAN_RING,
		type TreeLayout,
		type TreeState,
		type TreeStateInfo,
		type LabelItem
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
	/** Zoom bounds: 2.5 shows a leaf at 25px; past that only the labels would grow. */
	const ZOOM = { min: 0.1, max: 2.5 };
	/** The face is themed by <html data-theme>; the flow's chrome follows it (tokens do the rest). */
	const colorMode =
		typeof document !== 'undefined' && document.documentElement.dataset.theme === 'light'
			? 'light'
			: 'dark';

	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let phase = $state<'loading' | 'ok' | 'empty' | 'err'>('loading');
	let err = $state('');
	let source = $state<'keap' | 'fallback'>('keap');
	let table = $state.raw<DataTable | null>(null);
	let states = $state.raw(new Map<string, TreeStateInfo>());
	let layout = $state.raw<TreeLayout | null>(null);
	let labelItems = $state.raw<LabelItem[]>([]);
	let canWrite = $derived(table?.canWrite ?? false);
	let action = $state('');
	let hideDormant = $state(true); // queued/parked/dropped are a third of the board
	let selectedId = $state<string | null>(null);
	let hoverId = $state<string | null>(null);
	let focusId = $state<string | null>(null);
	/** Svelte Flow's viewport, bound: the label layer projects flow → screen with it. */
	let viewport = $state<Viewport | undefined>();
	const vp = $derived(viewport ?? { x: 0, y: 0, zoom: 0.4 });
	/** The pass reruns on a ~4 % zoom step, not on every wheel tick; boxes are placed at the exact zoom. */
	const zoomStep = $derived(Math.exp(Math.round(Math.log(vp.zoom) * 24) / 24));
	const pinned = $derived(new Set([hoverId, focusId, selectedId].filter((x): x is string => !!x)));
	const plan = $derived(labelPlan(labelItems, zoomStep, pinned));
	const labels = $derived(plan.map((b) => labelBox(b, vp.zoom)));
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
	const apex = new Map(ORGAN_RING.map((r) => [r.key, r]));

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
		const hidden = new Set<string>();
		const rowNodes: Node[] = [];
		for (const r of t.rows) {
			const pos = lay.positions.get(r.id);
			if (!pos) continue;
			const slug = text(r.slug);
			const info = st.get(slug);
			const state = info?.state ?? 'dormant';
			stateOf.set(r.id, state);
			const sys = apex.get(slug);
			const label = sys?.title || text(r.title) || slug || r.id;
			const rank = gemRank(slug, info, ring);
			const size = GEM_SIZE[rank];
			const hide = hideDormant && state === 'dormant' && !sys;
			if (hide) hidden.add(r.id);
			rowNodes.push({
				id: r.id,
				type: 'skill',
				position: { x: pos.x - size / 2, y: pos.y - size / 2 },
				width: size,
				height: size,
				data: { title: sys ? `${sys.title} — ${sys.tells}` : text(r.title) || slug },
				class: `skill rank-${rank} st-${state}${specClass(info)}`,
				ariaLabel: `${label} — ${state}${info?.ready === false ? ', needs a spec' : ''}${sys ? `. ${sys.tells}` : ''}${info?.blockedBy ? `, blocked by ${info.blockedBy}` : ''}`,
				hidden: hide
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
			position: { x: -GEM_SIZE.core / 2, y: -GEM_SIZE.core / 2 },
			width: GEM_SIZE.core,
			height: GEM_SIZE.core,
			data: { title: 'core — the shipped estate' },
			class: 'skill rank-core st-shipped',
			ariaLabel: 'core — the shipped estate',
			draggable: false,
			selectable: false,
			connectable: false,
			deletable: false
		};
		states = st;
		layout = lay;
		labelItems = skillTreeLabels(t.rows, lay, st).filter((i) => !hidden.has(i.id));
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

	/** Keyboard focus lands on Svelte Flow's node wrapper (data-id); pin that node's label. */
	function onfocusin(e: FocusEvent) {
		const el = e.target as HTMLElement | null;
		focusId = el?.closest?.('.svelte-flow__node')?.getAttribute('data-id') ?? null;
	}

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
		<div class="flow" {onfocusin} onfocusout={() => (focusId = null)}>
			<SvelteFlow
				bind:nodes
				bind:edges
				bind:viewport
				{nodeTypes}
				{colorMode}
				fitView
				fitViewOptions={{ padding: 0.15 }}
				minZoom={ZOOM.min}
				maxZoom={ZOOM.max}
				zoomOnDoubleClick={false}
				nodesDraggable={false}
				connectionMode={ConnectionMode.Loose}
				connectionRadius={24}
				onlyRenderVisibleElements
				nodesConnectable={canWrite}
				elementsSelectable={true}
				{onconnect}
				{ondelete}
				{onbeforedelete}
				onnodepointerenter={({ node }) => (hoverId = node.id)}
				onnodepointerleave={() => (hoverId = null)}
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
				<!-- The label layer: screen space, so text never scales; the nodes carry the aria names. -->
				<div class="labels" aria-hidden="true">
					{#each labels as l (l.id)}
						<span
							class="lbl {l.cls}"
							class:pinned={pinned.has(l.id)}
							style="left:{(vp.x + l.x).toFixed(1)}px; top:{(vp.y + l.y).toFixed(
								1
							)}px; max-width:{l.w}px">{l.text}</span
						>
					{/each}
				</div>
				<Controls showLock={false} />
				<MiniMap
					pannable
					zoomable
					nodeClass={(n) => String(n.class ?? '')}
					nodeStrokeWidth={20}
					nodeBorderRadius={20}
				/>
			</SvelteFlow>

			{#if selectedRow}
				<RowDetail row={selectedRow} onclose={() => (selectedId = null)}>
					{#if selectedInfo}
						<p class="state">
							<i class="dot st-{selectedInfo.state}"></i>{selectedInfo.state}
							{#if selectedInfo.system}· {selectedInfo.system}, ring {selectedInfo.depth + 1}{/if}
						</p>
						{#if selectedInfo.depth === 0}
							<p class="tells">{apex.get(selectedInfo.system)?.tells}</p>
						{/if}
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
	/* The field: a dark vignette lit from the core. */
	.flow :global(.svelte-flow) {
		background: radial-gradient(
			circle at 50% 50%,
			color-mix(in srgb, var(--ok) 9%, var(--bg)) 0,
			var(--bg) 50%,
			color-mix(in srgb, var(--bg) 85%, black) 100%
		);
	}
	.flow :global(.svelte-flow__background) {
		opacity: 0.3;
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

	/* ── The label layer: screen px, one line, ellipsis; the state tints the ink. ── */
	.labels {
		position: absolute;
		inset: 0;
		overflow: hidden;
		pointer-events: none;
		z-index: 4; /* over the renderer (4, earlier in the DOM), under the panels (5) */
	}
	.lbl {
		position: absolute;
		box-sizing: border-box;
		height: 18px; /* = LABEL_PX.small.h: the pass measures what is drawn */
		padding: 0 7px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--bg) 82%, transparent);
		border: 1px solid var(--glass-brd);
		color: var(--fg);
		font-size: 11px;
		line-height: 16px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.lbl.rank-system,
	.lbl.rank-core,
	.lbl.rim {
		height: 22px; /* = LABEL_PX.big.h */
		padding: 0 8px;
		font-size: 13px;
		font-weight: 600;
		line-height: 20px;
	}
	.lbl.rank-core {
		letter-spacing: 0.08em;
		text-transform: uppercase;
		font-size: 12px;
	}
	.lbl.rim {
		background: transparent;
		border-color: transparent;
		color: color-mix(in srgb, var(--fg) 70%, var(--muted));
		text-shadow: 0 0 12px var(--bg);
	}
	.lbl.st-frontier,
	.lbl.st-doing {
		color: var(--warn-ink);
	}
	.lbl.st-allocated,
	.lbl.st-review {
		color: var(--info-ink);
	}
	.lbl.st-blocked,
	.lbl.st-dormant,
	.lbl.rank-halo {
		color: var(--muted);
	}
	.lbl.pinned {
		border-color: var(--accent);
		color: var(--fg);
		z-index: 1;
	}

	/* ── Nodes. The box is the gem's size. State sets --node. ── */
	.flow :global(.svelte-flow__node.skill) {
		--node: var(--glass-brd);
		--node-core: color-mix(in srgb, var(--node) 30%, var(--bg));
		border-radius: 50%;
		background: transparent;
		border: 0;
		padding: 0;
		box-shadow: none;
		color: var(--fg);
		cursor: pointer;
	}
	.flow :global(.svelte-flow__node.skill:focus-visible) {
		outline: 2px solid var(--accent);
		outline-offset: 4px;
	}
	.flow :global(.svelte-flow__node.skill.selected .gem) {
		box-shadow:
			0 0 0 2px var(--bg),
			0 0 0 4px var(--accent),
			0 0 16px 4px color-mix(in srgb, var(--accent) 50%, transparent);
	}
	.flow :global(.svelte-flow__node.skill:hover),
	.flow :global(.svelte-flow__node.skill:focus-visible),
	.flow :global(.svelte-flow__node.skill.selected) {
		z-index: 20 !important;
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
	/* A keystone's halo (clip-path cuts a box-shadow, so the glow is the node's own). */
	.flow :global(.svelte-flow__node.rank-system) {
		border-radius: 50%;
		box-shadow: 0 0 22px 6px color-mix(in srgb, var(--node) 35%, transparent);
	}
	.flow :global(.svelte-flow__node.rank-epic .gem) {
		background: var(--node-core);
		box-shadow:
			inset 0 0 0 2px var(--node),
			0 0 8px 1px color-mix(in srgb, var(--node) 45%, transparent);
	}
	.flow :global(.svelte-flow__node.rank-leaf.st-shipped .gem),
	.flow :global(.svelte-flow__node.rank-leaf.st-allocated .gem) {
		box-shadow: 0 0 6px 1px color-mix(in srgb, var(--node) 60%, transparent);
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
		box-shadow: 0 0 8px 2px color-mix(in srgb, var(--node) 55%, transparent);
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

	/* Handles: both on the gem's centre (a 1px-tall box, so the edge's end IS the centre), with a
	   round hit area on hover; the connection snaps within connectionRadius, so a drop is forgiving. */
	.flow :global(.svelte-flow__node.skill .svelte-flow__handle) {
		top: 50%;
		left: 50%;
		right: auto;
		bottom: auto;
		width: 12px;
		height: 1px;
		min-width: 0;
		min-height: 0;
		border: 0;
		border-radius: 0;
		background: transparent;
		transform: translate(-50%, -50%);
	}
	.flow :global(.svelte-flow__node.skill .svelte-flow__handle::before) {
		content: '';
		position: absolute;
		inset: -8px -2px;
		border-radius: 50%;
	}
	.flow :global(.svelte-flow__node.skill:hover .svelte-flow__handle.source::before),
	.flow :global(.svelte-flow__node.skill.selected .svelte-flow__handle.source::before) {
		box-shadow: inset 0 0 0 1px var(--accent);
	}

	/* Connectors: allocated paths lit from the core outward; the frontier's own link dashed. */
	.flow :global(.svelte-flow__edge-path) {
		stroke: var(--glass-brd);
		stroke-width: 1;
	}
	.flow :global(.svelte-flow__edge.grown .svelte-flow__edge-path) {
		stroke: var(--ok);
		stroke-width: 2;
		stroke-opacity: 0.9;
		filter: drop-shadow(0 0 3px color-mix(in srgb, var(--ok) 70%, transparent));
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
		z-index: 6;
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
	.spec,
	.tells {
		margin: 0.4rem 0 0;
		color: var(--fg);
	}
	.blocker,
	.spec.needs,
	.tells {
		color: var(--muted);
	}
</style>
