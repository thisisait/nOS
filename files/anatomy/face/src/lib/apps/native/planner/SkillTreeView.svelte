<!--
  Planner — the roadmap as a passive skill tree (face-skill-tree-view; operator
  2026-11-13, row roadmap-organic-structure; redesign v2 2026-11-13).

  The core in the centre, the 13 apex organ systems as keystones on ring 1 (each in its
  own petal), every row growing outward from its system. A node's colour is its state
  under the frontier rule of tools/roadmap-status.py (frontierStates in
  $lib/tables/planner.ts): shipped and active rows are the allocated tree, drawn as lit
  connectors from the core; a frontier row with a ready spec (the loop builds it) is filled
  and pulses, one that needs a spec first is an open ring; a row under an ungrown ancestor
  is dim and its detail names the blocker. Milestones orbit the tree; rows that hang under
  no system form the dim halo outside it. The model is $lib/tables/skilltree/model.ts.

  Svelte Flow like the Roadmap graph, so drag-to-reparent is the same gesture over the
  same write: reparentPayload → tablesUpsertRow, gated by the BFF's canWrite. Rows are
  gems; names live in ONE screen-space label layer over the flow: every label is MEASURED
  in the font the browser resolved (canvas, calibrated against a DOM probe), wrapped by
  code and never clipped by CSS, hung outward from its gem, and thinned by a collision pass
  (pickLabels) so no label ever lies on another. Hover lights the path from the core; a
  selection dims the rest, leaves breadcrumbs on the ancestors and rings the blocker.
  Keys, scoped to this view: Tab reaches the tree once, ↑ ↓ ← → walk it, F finds the next
  spec-ready row, Enter selects, Esc clears. First load grows the tree from the core; a
  refresh diffs the snapshots in memory and lets rows ignite, sprout, wither or slide.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
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
	import { reparentPayload, ORGAN_RING, type TreeState } from '$lib/tables/planner';
	import { buildSnapshot, rimSeeds, type Snapshot } from '$lib/tables/skilltree/model';
	import { pickLabels, place, type LabelBox } from '$lib/tables/skilltree/labels';
	import { createBrowserMeasurer } from '$lib/tables/skilltree/measure';
	import { EDGE_Z } from '$lib/tables/skilltree/routing';
	import { wedgePath, DEFAULT_GUIDES } from '$lib/tables/skilltree/guides';
	import {
		ancestry,
		childrenMap,
		edgeKey,
		growIndex,
		parentMap,
		trace,
		type Trace
	} from '$lib/tables/skilltree/trace';
	import { navTarget, nextMatching } from '$lib/tables/skilltree/nav';
	import { diffSnapshots, FX_MS } from '$lib/tables/skilltree/evolution';
	import { tweenPolar } from '$lib/tables/skilltree/geom';
	import { CORE_ID, type TreeNode } from '$lib/tables/skilltree/types';
	import type { DataTable } from '$lib/contracts';
	import { StatusNote, Badge } from '$lib/components/ui';
	import RowDetail from './RowDetail.svelte';
	import SkillNode from './SkillNode.svelte';
	import SkillEdge from './SkillEdge.svelte';
	import FlowApi, { type FlowApi as Api } from './FlowApi.svelte';

	const nodeTypes = { skill: SkillNode };
	const edgeTypes = { skill: SkillEdge };
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
	const reduced =
		typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
	const apex = new Map(ORGAN_RING.map((r) => [r.key, r]));

	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let phase = $state<'loading' | 'ok' | 'empty' | 'err'>('loading');
	let err = $state('');
	let source = $state<'keap' | 'fallback'>('keap');
	let table = $state.raw<DataTable | null>(null);
	let snap = $state.raw<Snapshot | null>(null);
	let canWrite = $derived(table?.canWrite ?? false);
	let action = $state('');
	let hideDormant = $state(true); // queued/parked/dropped are a third of the board
	let selectedId = $state<string | null>(null);
	let hoverId = $state<string | null>(null);
	let focusId = $state(CORE_ID); // the one tab stop of the tree (roving tabindex)
	let growing = $state(false);
	let tweening = $state(false);
	let flowEl = $state<HTMLDivElement | undefined>();
	let api: Api | null = null; // the flow's instance API, for moving the camera
	let labelsEl = $state<HTMLDivElement | undefined>();
	/** Hidden probes with the real (scoped) label classes: the measurer calibrates against them. */
	let probeSmall = $state<HTMLElement | undefined>();
	let probeBig = $state<HTMLElement | undefined>();
	let probeRim = $state<HTMLElement | undefined>();
	/** Svelte Flow's viewport, bound. It MUST start as a real object: the store only writes a
	 *  bound viewport that is truthy, so an `undefined` start left the label layer at its
	 *  fallback forever while the nodes followed fitView (the v1 drift: names off their gems,
	 *  "The Watch" twice because the LOD thought the zoom was 0.4). */
	let viewport = $state<Viewport>({ x: 0, y: 0, zoom: 1 });
	/** The label pass reruns on a ~4 % zoom step, not on every wheel tick; place() re-anchors
	 *  per frame at the exact zoom. The quantised value is also the CSS --zoom. */
	const zq = $derived(Math.exp(Math.round(Math.log(viewport.zoom) * 24) / 24));

	const byId = $derived(new Map((snap?.nodes ?? []).map((n) => [n.id, n])));
	const parents = $derived(parentMap(snap?.edges ?? []));
	const children = $derived(childrenMap(snap?.edges ?? [], (id) => byId.get(id)));
	const visible = (n: TreeNode) => !(hideDormant && n.dormant);
	const hidden = $derived(new Set((snap?.nodes ?? []).filter((n) => !visible(n)).map((n) => n.id)));
	const lit = (id: string) => {
		const s = byId.get(id)?.state;
		return id === CORE_ID || s === 'shipped' || s === 'allocated';
	};
	const selectedNode = $derived(selectedId ? byId.get(selectedId) : undefined);
	const selectedRow = $derived(
		selectedId && table ? (table.rows.find((r) => r.id === selectedId) ?? null) : null
	);
	const selectedInfo = $derived(
		selectedId && snap ? snap.states.get(snap.slugOf.get(selectedId) ?? '') : undefined
	);
	const traced = $derived<Trace | null>(
		selectedId || hoverId ? trace((selectedId ?? hoverId)!, parents, lit) : null
	);
	const blocker = $derived(selectedId && traced?.blocker ? byId.get(traced.blocker) : undefined);
	/** Breadcrumbs: the selected row's ancestors (not the core, not keystones) keep their names. */
	const trail = $derived.by(() => {
		const t = new Set<string>();
		if (!selectedId) return t;
		for (const a of ancestry(selectedId, parents))
			if (a !== CORE_ID && byId.get(a)?.rank !== 'system') t.add(a);
		if (traced?.blocker) t.add(traced.blocker);
		return t;
	});
	const pinned = $derived(new Set([hoverId, selectedId].filter((x): x is string => !!x)));
	const count = (s: TreeState) => (snap?.nodes ?? []).filter((n) => n.state === s).length;
	const readyCount = $derived(
		(snap?.nodes ?? []).filter((n) => n.state === 'frontier' && n.spec === 'spec-ready').length
	);

	// ── labels: measured in the browser, picked on a zoom step, placed per frame ──
	let measurer = $state.raw<ReturnType<typeof createBrowserMeasurer> | null>(null);
	let fontTick = $state(0);
	$effect(() => {
		if (!labelsEl || !probeSmall || !probeBig || !probeRim || measurer) return;
		const probes = { small: probeSmall, big: probeBig, rim: probeRim };
		const m = createBrowserMeasurer((k) => probes[k]);
		measurer = m;
		const fonts = document.fonts;
		const again = () => {
			m.reset();
			fontTick++;
		};
		fonts?.ready.then(again);
		fonts?.addEventListener?.('loadingdone', again);
		return () => fonts?.removeEventListener?.('loadingdone', again);
	});
	const rim = $derived(snap ? rimSeeds(snap, visible) : null);
	const seeds = $derived(
		snap && rim ? [...snap.seeds.filter((s) => !hidden.has(s.id)), ...rim.seeds] : []
	);
	const boxes = $derived.by((): LabelBox[] => {
		void fontTick;
		if (!measurer || tweening) return [];
		return pickLabels(seeds, zq, { measurer, pinned, trail });
	});

	// ── guides: petals end at each sector's reach; rings, orbit, halo, hub ──
	const guides = $derived.by(() => {
		if (!snap || !rim) return null;
		const R = Math.max(
			snap.rings[snap.rings.length - 1],
			snap.orbit,
			snap.halo[snap.halo.length - 1] ?? 0,
			...rim.seeds.map((s) => Math.hypot(s.cx, s.cy))
		);
		const hub = snap.rings[1] * 0.55;
		return {
			R: R + 200,
			hub,
			wedges: snap.sectors.map((s) =>
				wedgePath(s, hub, (rim.reach.get(s.key) ?? hub) + DEFAULT_GUIDES.wedgePad)
			),
			rings: snap.rings.slice(1),
			orbit: snap.orbit,
			halo: snap.halo
		};
	});

	/** Svelte Flow's nodes and edges from the snapshot. The layout covers the FULL board
	 *  (positions do not jump when a filter changes); the dormant toggle only hides nodes,
	 *  and Svelte Flow hides their edges with them. `ghosts` are rows a refresh removed,
	 *  kept for FX_MS.wither so they can wither before they leave the DOM. */
	function toFlow(s: Snapshot, ghosts: TreeNode[] = []) {
		const grow = growIndex(
			s.nodes.map((n) => n.id),
			s.edges
		);
		const sel = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
		const rankOf = new Map(s.nodes.map((n) => [n.id, n.rank]));
		const mk = (n: TreeNode, extra = ''): Node => {
			const info = s.states.get(s.slugOf.get(n.id) ?? '');
			const sys = apex.get(s.slugOf.get(n.id) ?? '');
			const core = n.id === CORE_ID;
			return {
				id: n.id,
				type: 'skill',
				position: { x: n.x - n.size / 2, y: n.y - n.size / 2 },
				width: n.size,
				height: n.size,
				data: { title: n.title },
				class: `skill rank-${n.rank} st-${n.state}${n.spec ? ' ' + n.spec : ''}${extra}`,
				style: `--grow:${grow.get(n.id) ?? 0}`,
				ariaRole: 'button',
				ariaLabel: core
					? n.title
					: `${sys?.title ?? n.title} — ${n.state}${n.spec === 'spec-needed' ? ', needs a spec' : ''}${sys ? `. ${sys.tells}` : ''}${info?.blockedBy ? `, blocked by ${info.blockedBy}` : ''}`,
				hidden: !core && !visible(n),
				focusable: n.id === focusId,
				selected: sel.has(n.id),
				draggable: false,
				...(core ? { selectable: false, connectable: false, deletable: false } : {})
			};
		};
		nodes = [...s.nodes.map((n) => mk(n)), ...ghosts.map((n) => mk(n, ' fx-wither'))];
		edges = s.edges.map((e) => ({
			id: edgeKey(e),
			source: e.source,
			target: e.target,
			type: 'skill',
			class: e.cls,
			zIndex: EDGE_Z[e.cls] ?? 0,
			deletable: e.source !== CORE_ID,
			data: {
				sRank: rankOf.get(e.source) ?? 'leaf',
				tRank: rankOf.get(e.target) ?? 'leaf',
				grow: grow.get(e.target) ?? 0
			}
		}));
		return grow;
	}

	/** Hover and selection trace: toggled on the DOM, not by rebuilding 1100 node objects
	 *  (Svelte Flow rewrites a node's class only when its class string changes, so the marks
	 *  survive a selection toggle; a data refresh rebuilds and re-marks). */
	function markTrace(t: Trace | null) {
		const root = flowEl;
		if (!root) return;
		root
			.querySelectorAll('.svelte-flow__node.trace, .svelte-flow__edge.trace, .trace-blocker')
			.forEach((e) => e.classList.remove('trace', 'trace-blocker'));
		if (!t) return;
		const q = (sel: string) => root.querySelector(sel);
		for (const id of t.nodes)
			q(`.svelte-flow__node[data-id="${CSS.escape(id)}"]`)?.classList.add('trace');
		for (const k of t.edges)
			q(`.svelte-flow__edge[data-id="${CSS.escape(k)}"]`)?.classList.add('trace');
		if (t.blocker)
			q(`.svelte-flow__node[data-id="${CSS.escape(t.blocker)}"]`)?.classList.add('trace-blocker');
	}
	$effect(() => {
		const t = traced;
		void nodes;
		void edges;
		tick().then(() => markTrace(t));
	});

	/** A one-shot effect class on a node or edge g, removed after `ms` (spec/05 §4). */
	function fx(sel: string, cls: string, ms: number, delay = 0) {
		if (reduced) return;
		setTimeout(() => {
			const el = flowEl?.querySelector(sel);
			if (!el) return;
			el.classList.remove(cls);
			void (el as HTMLElement).offsetWidth;
			el.classList.add(cls);
			setTimeout(() => el.classList.remove(cls), ms);
		}, delay);
	}
	const nodeSel = (id: string) => `.svelte-flow__node[data-id="${CSS.escape(id)}"]`;
	const edgeSel = (k: string) => `.svelte-flow__edge[data-id="${CSS.escape(k)}"]`;

	/** The grow intro: the tree draws itself from the core outward (skipped under reduced motion). */
	function playGrow(grow: Map<string, number>) {
		if (reduced) return;
		const maxGrow = Math.max(0, ...grow.values());
		growing = false;
		void flowEl?.offsetWidth;
		growing = true;
		setTimeout(() => (growing = false), maxGrow * FX_MS.growStep + FX_MS.growDraw + 900);
	}

	/** Moved rows slide along the tree's own geometry (radius and bearing tween separately),
	 *  so a row shifted to a neighbouring slot never cuts a chord across the tree. Edges follow
	 *  (SkillEdge derives from the live endpoints); labels hide and re-pick when it settles. */
	function tweenMoved(
		moved: { id: string; from: { x: number; y: number }; to: { x: number; y: number } }[]
	) {
		if (!moved.length || reduced) return;
		tweening = true;
		const size = new Map(moved.map((m) => [m.id, byId.get(m.id)?.size ?? 10]));
		const t0 = performance.now();
		const step = (now: number) => {
			const t = Math.min(1, (now - t0) / FX_MS.move);
			const e = 1 - (1 - t) ** 3; // ease-out
			const at = new Map(moved.map((m) => [m.id, tweenPolar(m.from, m.to, e)]));
			nodes = nodes.map((n) => {
				const p = at.get(n.id);
				if (!p) return n;
				const s = size.get(n.id)!;
				return { ...n, position: { x: p.x - s / 2, y: p.y - s / 2 } };
			});
			if (t < 1) requestAnimationFrame(step);
			else tweening = false;
		};
		requestAnimationFrame(step);
	}

	/** Apply a (re)loaded table. The first snapshot grows; a later one is diffed in memory
	 *  against the previous: shipped rows ignite (inner rings first), new rows sprout, removed
	 *  rows wither as ghosts, other state changes flash, moved rows slide. */
	async function applyTree(t: DataTable) {
		const prev = snap;
		const next = buildSnapshot(t.rows, prev?.angles ?? null);
		snap = next;
		phase = t.rows.length ? 'ok' : 'empty';
		if (!prev || reduced) {
			const grow = toFlow(next);
			if (!prev) {
				await tick();
				playGrow(grow);
			}
			return;
		}
		const d = diffSnapshots(prev, next);
		// 1. the new state, with the moved rows still at their old place (they tween from there)
		toFlow(next, d.withered);
		if (d.moved.length) {
			const from = new Map(d.moved.map((m) => [m.id, m.from]));
			nodes = nodes.map((n) => {
				const p = from.get(n.id);
				return p
					? { ...n, position: { x: p.x - (n.width ?? 10) / 2, y: p.y - (n.height ?? 10) / 2 } }
					: n;
			});
		}
		await tick();
		// 2. one-shot effects, staggered inner rings first
		d.ignited.forEach((id, i) => {
			fx(nodeSel(id), 'fx-ignite', FX_MS.ignite, i * 120);
			const p = parents.get(id);
			if (p) fx(edgeSel(`${p}>${id}`), 'fx-ignite', FX_MS.ignite, i * 120);
		});
		d.sprouted.forEach((id, i) => fx(nodeSel(id), 'fx-sprout', FX_MS.sprout, 300 + i * 120));
		for (const s of d.shifted) fx(nodeSel(s.id), 'fx-shift', FX_MS.shift);
		// 3. the slide; 4. the ghosts leave the DOM once withered
		tweenMoved(d.moved);
		if (d.withered.length) setTimeout(() => snap === next && toFlow(next), FX_MS.wither);
	}

	async function load() {
		if (!snap) phase = 'loading';
		try {
			const t = await loadTable('roadmap');
			source = t.source;
			table = t;
			await applyTree(t);
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
		if (conn.source === CORE_ID || conn.target === CORE_ID) return; // the core is not a row
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
		for (const e of deleted.edges ?? []) if (e.source !== CORE_ID) void reparent(e.target, null);
	}

	// ── selection, focus, camera ──
	function select(id: string | null) {
		const want = id && id !== CORE_ID ? id : null;
		nodes = nodes.map((n) =>
			!!n.selected !== (n.id === want) ? { ...n, selected: n.id === want } : n
		);
		selectedId = want;
	}

	/** One tab stop for the whole tree: `focusable` moves to the new node, then it takes focus. */
	async function setFocus(id: string, move = true) {
		if (id === focusId && !move) return;
		const was = focusId;
		focusId = id;
		nodes = nodes.map((n) => (n.id === was || n.id === id ? { ...n, focusable: n.id === id } : n));
		if (!move) return;
		await tick();
		(flowEl?.querySelector(nodeSel(id)) as HTMLElement | null)?.focus({ preventScroll: true });
	}

	/** Pan to a node when it is within 90 px of the pane's edge, raising the zoom to `minZoom`. */
	function centreOn(id: string, minZoom = 0) {
		const n = byId.get(id);
		if (!n || !flowEl) return;
		const b = flowEl.getBoundingClientRect();
		const z = Math.max(viewport.zoom, minZoom);
		const sx = viewport.x + n.x * viewport.zoom;
		const sy = viewport.y + n.y * viewport.zoom;
		if (z === viewport.zoom && sx > 90 && sx < b.width - 90 && sy > 90 && sy < b.height - 90)
			return;
		void api?.setViewport(
			{ zoom: z, x: b.width / 2 - n.x * z, y: b.height / 2 - n.y * z },
			{ duration: reduced ? 0 : 250 }
		);
	}

	/** Keys, scoped to the view (capture phase, so Svelte Flow's own Enter/Esc handling on the
	 *  node does not double up): ↑ ↓ ← → walk the tree, F the next spec-ready frontier row,
	 *  Enter / Space select, Esc clears. Anything else passes through untouched. */
	function onkeydown(e: KeyboardEvent) {
		const tgt = e.target as HTMLElement | null;
		if (tgt && /^(INPUT|TEXTAREA|SELECT)$/.test(tgt.tagName)) return;
		if (e.key === 'Escape') {
			if (!selectedId) return;
			select(null);
		} else if (e.key === 'Enter' || e.key === ' ') {
			if (!tgt?.closest('.svelte-flow__node')) return;
			select(focusId === selectedId ? null : focusId);
		} else {
			if (!tgt?.closest('.svelte-flow__node')) return;
			let to: string | null = null;
			if (e.key.startsWith('Arrow')) to = navTarget(focusId, e.key, { parents, children });
			else if (e.key === 'f' || e.key === 'F')
				to = nextMatching(
					(snap?.nodes ?? []).map((n) => n.id),
					focusId,
					(id) => {
						const n = byId.get(id)!;
						return n.state === 'frontier' && n.spec === 'spec-ready' && visible(n);
					}
				);
			if (!to) return;
			void setFocus(to);
			hoverId = to;
			centreOn(to, byId.get(to)?.rank === 'leaf' || byId.get(to)?.rank === 'halo' ? 1 : 0.6);
		}
		e.preventDefault();
		e.stopPropagation();
	}

	/** Keyboard focus lands on Svelte Flow's node wrapper (data-id): it becomes the tab stop. */
	function onfocusin(e: FocusEvent) {
		const id = (e.target as HTMLElement | null)
			?.closest?.('.svelte-flow__node')
			?.getAttribute('data-id');
		if (id && id !== focusId) void setFocus(id, false);
	}

	onMount(() => {
		void load();
		if (import.meta.env.DEV) {
			// Acceptance hooks (dev build only; ACCEPTANCE.md §A): window.__skillTree.setView(z, wx, wy)
			const w = window as unknown as Record<string, unknown>;
			w.__skillTree = {
				setView: (z: number, wx = 0, wy = 0) => {
					const b = flowEl!.getBoundingClientRect();
					return api?.setViewport({ zoom: z, x: b.width / 2 - wx * z, y: b.height / 2 - wy * z });
				},
				select,
				hover: (id: string | null) => (hoverId = id),
				grow: () =>
					playGrow(
						growIndex(
							(snap?.nodes ?? []).map((n) => n.id),
							snap?.edges ?? []
						)
					)
			};
			return () => delete w.__skillTree;
		}
	});
</script>

<div class="tree">
	<header>
		<strong>Skill tree</strong>
		<span class="sub">{canWrite ? 'drag a handle to re-hang a row' : 'read-only'}</span>
		{#if source === 'fallback'}<Badge tone="warn">KEAP down — fallback</Badge>{/if}
		{#if snap?.absent.length}<Badge tone="warn">ring incomplete: {snap.absent.join(', ')}</Badge
			>{/if}
		{#if action}<span class="action" class:err={action !== 'saving…'}>{action}</span>{/if}
		<span class="tally">
			<span>{count('frontier')} frontier ({readyCount} spec ready)</span>
			<span>{count('blocked')} blocked</span>
			<span>{count('ungrown')} outside the ring</span>
			<label class="chk"
				><input type="checkbox" bind:checked={hideDormant} onchange={() => snap && toFlow(snap)} /> hide
				queued</label
			>
		</span>
		{#if !reduced}
			<button
				class="ctl grow"
				onclick={() =>
					playGrow(
						growIndex(
							(snap?.nodes ?? []).map((n) => n.id),
							snap?.edges ?? []
						)
					)}
				aria-label="Replay the grow intro">▶ grow</button
			>
		{/if}
		<button class="ctl refresh" onclick={load} aria-label="Reload the roadmap">↻</button>
	</header>

	{#if phase === 'loading'}
		<StatusNote kind="loading" title="Loading">Reading the roadmap DataTable…</StatusNote>
	{:else if phase === 'err'}
		<StatusNote kind="error" title="Could not read the roadmap">{err}</StatusNote>
	{:else if phase === 'empty'}
		<StatusNote kind="empty" title="No rows">The roadmap table is empty.</StatusNote>
	{:else}
		<div
			class="flow"
			class:tracing={!!selectedId}
			class:fx-grow={growing}
			style:--zoom={zq.toFixed(4)}
			bind:this={flowEl}
			{onfocusin}
			onkeydowncapture={onkeydown}
		>
			<SvelteFlow
				bind:nodes
				bind:edges
				bind:viewport
				{nodeTypes}
				{edgeTypes}
				{colorMode}
				fitView
				fitViewOptions={{ padding: 0.15 }}
				minZoom={ZOOM.min}
				maxZoom={ZOOM.max}
				zoomOnDoubleClick={false}
				nodesDraggable={false}
				nodesFocusable={false}
				connectionMode={ConnectionMode.Loose}
				connectionRadius={24}
				nodesConnectable={canWrite}
				elementsSelectable={true}
				{onconnect}
				{ondelete}
				{onbeforedelete}
				onnodepointerenter={({ node }) => (hoverId = node.id)}
				onnodepointerleave={() => (hoverId = null)}
				onselectionchange={({ nodes: sel }) => (selectedId = sel[0]?.id ?? null)}
			>
				<FlowApi onready={(a) => (api = a)} />
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
							<circle r={guides.hub} class="hub" />
						</svg>
					</ViewportPortal>
				{/if}
				<!-- The label layer: screen space, so text never scales; the nodes carry the aria names. -->
				<div class="labels" aria-hidden="true" bind:this={labelsEl}>
					<span class="lbl rank-leaf probe" bind:this={probeSmall}>probe</span>
					<span class="lbl rank-system probe" bind:this={probeBig}>probe</span>
					<span class="lbl rim probe" bind:this={probeRim}>probe</span>
					{#each boxes as b (b.seed.id)}
						{@const p = place(b.seed, b.wrapped, viewport.zoom)}
						<span
							class="lbl {b.seed.cls} al-{p.align}"
							class:pinned={pinned.has(b.seed.id)}
							class:trail={trail.has(b.seed.id)}
							class:cut={b.wrapped.truncated}
							style:left="{(viewport.x + p.x).toFixed(1)}px"
							style:top="{(viewport.y + p.y).toFixed(1)}px">{b.wrapped.lines.join('\n')}</span
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
				<RowDetail row={selectedRow} onclose={() => select(null)}>
					{#if selectedInfo}
						<p class="state">
							<i class="dot st-{selectedInfo.state}"></i>{selectedInfo.state}
							{#if selectedInfo.system}· {apex.get(selectedInfo.system)?.title ??
									selectedInfo.system}, ring {selectedInfo.depth + 1}{/if}
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
						{#if blocker}
							<p class="blocker">grows first: {blocker.title}</p>
						{/if}
						{#if selectedNode}
							<p class="blocker">
								path: {ancestry(selectedNode.id, parents).length} steps from the core
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
	/* ===== The skill tree, glass-face theme (skill-tree v2). Colour from tokens only; every
	   new shade is a color-mix() of tokens; red (--bad) appears only on st-ungrown (a state).
	   Nothing dashed: dashed means UNKNOWN in this design system.
	   .flow carries --zoom (quantised): strokes keep ≥ 1 screen px, gems a minimum on-screen
	   size at fit (--min), the rim and the guides fade by zoom.
	   A gem reads on three channels, so no state rests on hue alone: fill pattern (solid ·
	   solid+pip · half · open ring · ring+pip · empty), setting (lit = state colour · unlit =
	   line-hi), motion/aura (only spec-ready pulses; only allocated-path gems carry an aura). */

	/* Chrome */
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
		padding: 0.45rem 0.75rem;
		border-bottom: 1px solid var(--glass-brd);
		flex: 0 0 auto;
	}
	header strong {
		font-family: var(--font-code);
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.16em;
		text-transform: uppercase;
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
		gap: 0.75rem;
		font-variant-numeric: tabular-nums;
	}
	.chk {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		white-space: nowrap;
	}
	.ctl {
		background: transparent;
		border: 1px solid var(--glass-brd);
		color: var(--fg);
		border-radius: 6px;
		cursor: pointer;
		padding: 0.15rem 0.5rem;
		font-size: 0.8rem;
	}
	.ctl:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	/* The field: a deep ground, lit from the core, an aurora at the rim. */
	.flow {
		flex: 1 1 auto;
		min-height: 0;
		position: relative;
	}
	.flow :global(.svelte-flow) {
		background:
			radial-gradient(
				ellipse 80% 75% at 50% 50%,
				transparent 45%,
				color-mix(in srgb, var(--glow-2) 28%, transparent) 100%
			),
			radial-gradient(
				circle at 50% 50%,
				color-mix(in srgb, var(--glow) 20%, var(--bg)) 0,
				var(--bg) 60%
			);
	}
	.flow :global(.svelte-flow__background) {
		opacity: 0.12;
	}

	/* Guides — engraved into the ground, never louder than a gem. Strokes keep ≥ 1 screen px.
	   Draw order (the CSS counts circles): wedges, rings from ring 1 out, orbit, halo, hub. */
	.guides {
		position: absolute;
		pointer-events: none;
	}
	.guides .wedge {
		fill: var(--fg);
		fill-opacity: 0.012;
		stroke: var(--fg);
		stroke-opacity: 0.05;
		stroke-width: max(1px, calc(1px / var(--zoom, 1)));
		stroke-linejoin: round;
	}
	.guides .wedge.alt {
		fill-opacity: 0.03;
	}
	.guides .ring {
		fill: none;
		stroke: var(--fg);
		stroke-opacity: 0.045;
		stroke-width: max(1px, calc(1px / var(--zoom, 1)));
	}
	/* The first ring circle is ring 1, the keystone ring: lit, it carries the 13 systems. */
	.guides .ring:nth-of-type(1) {
		stroke: var(--ok);
		stroke-opacity: 0.22;
		stroke-width: max(1.5px, calc(1px / var(--zoom, 1)));
	}
	/* The outer rings sit close together: let them recede. */
	.guides .ring:nth-of-type(n + 5) {
		stroke-opacity: 0.028;
	}
	.guides .hub {
		fill: color-mix(in srgb, var(--ok) 5%, transparent);
		stroke: color-mix(in srgb, var(--ok) 38%, transparent);
		stroke-width: max(1.5px, calc(1px / var(--zoom, 1)));
	}
	.guides .orbit {
		fill: none;
		stroke: var(--fg);
		stroke-opacity: 0.3;
		stroke-width: max(2px, calc(1.6px / var(--zoom, 1)));
		stroke-linecap: round;
		stroke-dasharray: 0 18; /* dots, not dashes: round caps on a zero-length dash */
	}
	.guides .halo {
		fill: none;
		stroke: var(--bad);
		stroke-opacity: 0.14;
		stroke-width: max(1.5px, calc(1.2px / var(--zoom, 1)));
		stroke-linecap: round;
		stroke-dasharray: 0 12;
	}

	/* Labels — measured, never estimated; wrapped, never clipped. The view measures each string
	   in the font the browser resolved, breaks small labels into lines itself and writes them
	   joined by "\n": white-space: pre, no max-width, no text-overflow, overflow visible. Box
	   metrics MUST match BOX in skilltree/labels.ts (padding + 1px border = padX/padY, line-height
	   = lineH): small 8/2/14 · big 9/1/20 · rim 9/1/22. No pills: a borderless plate of the
	   ground plus a text halo; the bordered card is reserved for the pinned label. */
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
		padding: 1px 7px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: color-mix(in srgb, var(--bg) 55%, transparent);
		color: var(--ink-mute);
		font-size: 11px;
		font-weight: 400;
		line-height: 14px;
		white-space: pre;
		overflow: visible;
		text-shadow:
			0 0 2px var(--bg),
			0 0 4px var(--bg),
			0 0 9px var(--bg);
	}
	.lbl.probe {
		left: -10000px;
		top: 0;
		visibility: hidden;
	}
	.lbl.al-end {
		text-align: right;
	}
	.lbl.al-mid {
		text-align: center;
	}
	.lbl.rank-system,
	.lbl.rank-core {
		padding: 0 8px;
		font-family: var(--font-code);
		font-size: 11px;
		font-weight: 600;
		line-height: 20px;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--fg);
	}
	.lbl.rank-core {
		color: var(--ok-ink);
	}
	.lbl.rim {
		padding: 0 8px;
		font-family: var(--font-code);
		font-size: 12px;
		font-weight: 600;
		line-height: 22px;
		letter-spacing: 0.24em;
		text-transform: uppercase;
		background: transparent;
		color: color-mix(in srgb, var(--muted) 55%, var(--fg));
		text-shadow:
			0 0 3px var(--bg),
			0 0 14px var(--bg);
		/* Region names belong to the far view: they fade as you zoom in (LOD hides them at 0.55). */
		opacity: clamp(0.55, calc(1.5 - var(--zoom, 0.3) * 1.6), 1);
	}
	/* Tone by state — the label repeats the gem's channel, never contradicts it. */
	.lbl.st-allocated {
		color: var(--info-ink);
	}
	.lbl.st-frontier,
	.lbl.st-doing {
		color: var(--warn-ink);
	}
	.lbl.st-review {
		color: color-mix(in srgb, var(--data-4) 45%, var(--fg));
	}
	.lbl.st-milestone {
		color: var(--fg);
	}
	.lbl.st-blocked,
	.lbl.st-dormant,
	.lbl.rank-halo {
		color: var(--muted);
	}
	.lbl.st-ungrown {
		color: var(--bad-ink);
	}
	/* Breadcrumbs: the selected row's ancestors keep their names on screen at any zoom. */
	.lbl.trail {
		color: var(--fg);
	}
	/* Pinned (hovered / selected): the full title as a small glass card, up to 12 lines. */
	.lbl.pinned {
		z-index: 1;
		padding: 4px 9px;
		margin: -3px -2px;
		line-height: 14px;
		background: color-mix(in srgb, var(--bg) 90%, transparent);
		border-color: var(--accent);
		color: var(--fg);
		text-shadow: none;
		box-shadow:
			0 0 0 2px color-mix(in srgb, var(--accent) 22%, transparent),
			0 6px 18px color-mix(in srgb, var(--bg) 80%, transparent);
	}

	/* Nodes. Each node defines its palette once; the gem paints with it.
	     --node   the state colour            --fill   the gem's face (pattern by state)
	     --frame  the setting ring            --aura   a faked glow (gradient, not blur)
	     --min    minimum on-screen scale factor at low zoom (screen size ≥ box × --min) */
	.flow :global(.svelte-flow__node.skill) {
		--node: var(--line-hi);
		--node-core: color-mix(in srgb, var(--node) 20%, var(--bg));
		--lit: color-mix(in srgb, var(--node) 50%, var(--fg));
		--gem-lit: radial-gradient(
			circle at 36% 30%,
			var(--lit) 0,
			var(--node) 42%,
			color-mix(in srgb, var(--node) 55%, var(--bg)) 100%
		);
		--fill: var(--node-core);
		--frame: color-mix(in srgb, var(--line-hi) 60%, var(--bg));
		--aura: transparent;
		--min: 0.34;
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
		outline-offset: 5px;
	}
	.flow :global(.svelte-flow__node.skill:hover),
	.flow :global(.svelte-flow__node.skill:focus-visible),
	.flow :global(.svelte-flow__node.skill.selected) {
		z-index: 20 !important;
	}

	/* States → palette. */
	.flow :global(.svelte-flow__node.st-shipped) {
		--node: var(--ok);
		--fill: var(--gem-lit);
		--frame: color-mix(in srgb, var(--node) 70%, var(--fg));
		--aura: color-mix(in srgb, var(--node) 34%, transparent);
	}
	/* Active: allocated in a different tone — blue, with a white-hot pip (work in the forge). */
	.flow :global(.svelte-flow__node.st-allocated) {
		--node: var(--info);
		--fill:
			radial-gradient(
				circle closest-side,
				color-mix(in srgb, var(--fg) 88%, var(--node)) 0 22%,
				transparent 34%
			),
			var(--gem-lit);
		--frame: color-mix(in srgb, var(--node) 70%, var(--fg));
		--aura: color-mix(in srgb, var(--node) 30%, transparent);
	}
	/* Frontier, spec ready: the only filled amber gem, the only motion on screen. */
	.flow :global(.svelte-flow__node.st-frontier) {
		--node: var(--warn);
		--fill: var(--gem-lit);
		--frame: var(--warn);
		--aura: color-mix(in srgb, var(--node) 45%, transparent);
	}
	/* Frontier, needs a spec: an amber ring left open — buildable, not yet. Unlit setting, no aura. */
	.flow :global(.svelte-flow__node.st-frontier.spec-needed) {
		--fill:
			radial-gradient(circle closest-side, var(--node-core) 0 64%, transparent 66%),
			conic-gradient(from 40deg, var(--node) 0 280deg, transparent 0);
		--frame: color-mix(in srgb, var(--line-hi) 60%, var(--bg));
		--aura: transparent;
	}
	/* Doing: amber, half full — filling up. Lit setting, no pulse. */
	.flow :global(.svelte-flow__node.st-doing) {
		--node: var(--warn);
		--fill: linear-gradient(to top, var(--node) 0 50%, var(--node-core) 50%);
		--frame: var(--warn);
	}
	/* Review: violet ring with a pip — finished, waiting for a look. */
	.flow :global(.svelte-flow__node.st-review) {
		--node: var(--data-4);
		--fill: radial-gradient(
			circle closest-side,
			var(--node) 0 30%,
			var(--node-core) 36% 60%,
			var(--node) 66%
		);
		--frame: color-mix(in srgb, var(--node) 55%, var(--line-hi));
	}
	.flow :global(.svelte-flow__node.st-blocked) {
		--node: var(--line-hi);
		--fill: var(--node-core);
		opacity: 0.42;
	}
	.flow :global(.svelte-flow__node.st-dormant) {
		--node: var(--ink-faint);
		--fill: var(--ink-faint);
		--frame: transparent;
		opacity: 0.6;
	}
	.flow :global(.svelte-flow__node.st-milestone) {
		--node: var(--fg);
		--frame: var(--line-hi);
	}
	.flow :global(.svelte-flow__node.st-ungrown) {
		--node: var(--bad);
		--fill: radial-gradient(circle closest-side, var(--bad-soft) 0 58%, var(--node) 64%);
		--frame: transparent;
	}

	/* Ranks → shape. Leaf: a small passive. Gem in a thin setting; a dark gap (--bg) is the
	   socket the path enters, so lines read as joined rather than passing behind a dot. */
	.flow :global(.svelte-flow__node.rank-leaf .gem),
	.flow :global(.svelte-flow__node.rank-halo .gem) {
		background: var(--fill);
		box-shadow:
			0 0 0 1.5px var(--bg),
			0 0 0 2.5px var(--frame);
	}
	.flow :global(.svelte-flow__node.rank-halo) {
		--min: 0.3;
		opacity: 0.72;
	}
	.flow :global(.svelte-flow__node.rank-halo .gem) {
		box-shadow:
			0 0 0 1px var(--bg),
			0 0 0 2px var(--frame);
	}
	.flow :global(.svelte-flow__node.rank-halo.st-dormant) {
		opacity: 0.4;
	}
	/* Epic: a notable. Heavier setting plus a fine outer ring. */
	.flow :global(.svelte-flow__node.rank-epic) {
		--min: 0.36;
	}
	.flow :global(.svelte-flow__node.rank-epic .gem) {
		background: var(--fill);
		box-shadow:
			0 0 0 2px var(--bg),
			0 0 0 3.5px var(--frame),
			0 0 0 5px var(--bg);
	}
	.flow :global(.svelte-flow__node.rank-epic .gem::after) {
		content: '';
		position: absolute;
		inset: -7px;
		border-radius: 50%;
		border: 1px solid color-mix(in srgb, var(--frame) 50%, transparent);
		pointer-events: none;
	}
	/* Aura: a gradient disc behind the gem (no blur), only on the allocated path and spec-ready. */
	.flow
		:global(
			.svelte-flow__node:is(.rank-leaf, .rank-epic, .rank-halo):is(
					.st-shipped,
					.st-allocated,
					.st-frontier:not(.spec-needed)
				)
				.gem::before
		) {
		content: '';
		position: absolute;
		inset: -90%;
		border-radius: 50%;
		background: radial-gradient(circle closest-side, var(--aura), transparent);
		z-index: -1;
		pointer-events: none;
	}
	/* Milestone: a diamond in a diamond, on the orbit beyond the tree (rotate keeps transform free). */
	.flow :global(.svelte-flow__node.st-milestone .gem) {
		border-radius: 2px;
		rotate: 45deg;
		background: var(--node-core);
		box-shadow:
			inset 0 0 0 1.5px var(--node),
			inset 0 0 0 3.5px var(--node-core),
			inset 0 0 0 7px color-mix(in srgb, var(--node) 75%, transparent),
			0 0 0 2px var(--bg),
			0 0 14px 2px color-mix(in srgb, var(--node) 16%, transparent);
	}
	.flow :global(.svelte-flow__node.st-milestone .gem::after) {
		inset: -6px;
		border-radius: 2px;
		border-color: color-mix(in srgb, var(--line-hi) 70%, transparent);
	}
	/* System: the keystone. A hexagon cut in three — lit rim, dark band, lit stone — inside a
	   fine orbit ring, with the node's own halo (clip-path would cut a gem shadow). */
	.flow :global(.svelte-flow__node.rank-system) {
		--min: 0.42;
		--frame: color-mix(in srgb, var(--node) 70%, var(--fg));
		box-shadow: 0 0 28px 8px color-mix(in srgb, var(--node) 30%, transparent);
	}
	.flow :global(.svelte-flow__node.rank-system::before) {
		content: '';
		position: absolute;
		inset: -11px;
		border-radius: 50%;
		border: 1px solid color-mix(in srgb, var(--node) 45%, transparent);
		background: radial-gradient(circle closest-side, var(--bg) 0 70%, transparent 100%);
		pointer-events: none;
	}
	.flow :global(.svelte-flow__node.rank-system .gem) {
		border-radius: 0;
		clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
		background: linear-gradient(
			160deg,
			var(--lit),
			var(--frame) 40%,
			color-mix(in srgb, var(--node) 45%, var(--bg))
		);
	}
	.flow :global(.svelte-flow__node.rank-system .gem::before),
	.flow :global(.svelte-flow__node.rank-system .gem::after) {
		content: '';
		position: absolute;
		clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
	}
	.flow :global(.svelte-flow__node.rank-system .gem::before) {
		inset: 2.5px;
		background: var(--bg);
	}
	.flow :global(.svelte-flow__node.rank-system .gem::after) {
		inset: 6px;
		background: var(--gem-lit);
	}
	/* Core: the shipped estate. A lit stone, a dark band, a ring of 13 ticks (one per system). */
	.flow :global(.svelte-flow__node.rank-core) {
		--node: var(--ok);
		--min: 0.5;
		box-shadow:
			0 0 44px 12px var(--ok-soft),
			0 0 140px 70px color-mix(in srgb, var(--glow) 45%, transparent);
	}
	.flow :global(.svelte-flow__node.rank-core::before) {
		content: '';
		position: absolute;
		inset: -18px;
		border-radius: 50%;
		border: 1px solid color-mix(in srgb, var(--ok) 42%, transparent);
		pointer-events: none;
	}
	.flow :global(.svelte-flow__node.rank-core .gem) {
		background:
			radial-gradient(
				circle at 44% 40%,
				color-mix(in srgb, var(--ok) 35%, var(--fg)) 0 4%,
				transparent 9%
			),
			radial-gradient(
				circle closest-side,
				var(--ok) 0 30%,
				color-mix(in srgb, var(--ok) 45%, var(--bg)) 42%,
				var(--bg) 46% 61%,
				transparent 62%
			),
			repeating-conic-gradient(from -90deg, var(--ok) 0 4deg, transparent 4deg calc(360deg / 13)),
			var(--bg);
		box-shadow:
			0 0 0 2px var(--bg),
			0 0 0 3.5px var(--ok),
			0 0 0 7px var(--bg),
			0 0 0 8px color-mix(in srgb, var(--ok) 45%, transparent);
	}

	/* Frontier, spec ready: a steady amber halo plus one expanding ring (the only loop on screen). */
	.flow :global(.svelte-flow__node.st-frontier:not(.spec-needed)) {
		box-shadow: 0 0 14px 4px color-mix(in srgb, var(--warn) 40%, transparent);
	}
	.flow :global(.svelte-flow__node.st-frontier:not(.spec-needed)::after) {
		content: '';
		position: absolute;
		inset: -4px;
		border-radius: 50%;
		border: 1.5px solid var(--warn);
		pointer-events: none;
		animation: pulse 2.6s cubic-bezier(0.2, 0.6, 0.3, 1) infinite;
	}
	@keyframes pulse {
		0% {
			transform: scale(0.85);
			opacity: 0.95;
		}
		100% {
			transform: scale(2.4);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.flow :global(.svelte-flow__node.st-frontier:not(.spec-needed)::after) {
			animation: none;
			transform: scale(1.5);
			opacity: 0.6;
		}
	}

	/* Selection: shadow-lit, on the node (round) so the hex keystone shows it too. */
	.flow :global(.svelte-flow__node.skill.selected) {
		box-shadow:
			0 0 0 3px var(--bg),
			0 0 0 5px color-mix(in srgb, var(--accent) 80%, transparent),
			0 0 24px 6px color-mix(in srgb, var(--accent) 35%, transparent);
	}
	.flow :global(.svelte-flow__node.skill.rank-leaf.selected),
	.flow :global(.svelte-flow__node.skill.rank-halo.selected) {
		box-shadow:
			0 0 0 4px var(--bg),
			0 0 0 6px color-mix(in srgb, var(--accent) 80%, transparent),
			0 0 20px 6px color-mix(in srgb, var(--accent) 35%, transparent);
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

	/* Connectors. Every link is the same carved channel; allocation lights it. Plain = an unlit
	   groove; grown = the lit path (the only stroke with a glow: the performance budget); front =
	   an amber spark into the frontier. Paint order on a shared trunk: plain < front < grown
	   (edge zIndex). */
	.flow :global(.svelte-flow__edge-path) {
		fill: none;
		stroke: color-mix(in srgb, var(--line-hi) 36%, transparent);
		stroke-width: max(1.5px, calc(1px / var(--zoom, 1)));
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.flow :global(.svelte-flow__edge.grown .svelte-flow__edge-path) {
		stroke: var(--ok);
		stroke-width: max(3px, calc(1.8px / var(--zoom, 1)));
		filter: drop-shadow(0 0 3px color-mix(in srgb, var(--ok) 60%, transparent));
	}
	.flow :global(.svelte-flow__edge.front .svelte-flow__edge-path) {
		stroke: color-mix(in srgb, var(--warn) 72%, transparent);
		stroke-width: max(2px, calc(1.3px / var(--zoom, 1)));
	}
	.flow :global(.svelte-flow__edge.selected .svelte-flow__edge-path) {
		stroke: var(--accent);
		stroke-width: max(3px, calc(2px / var(--zoom, 1)));
	}

	/* Trace — the path you would have to allocate. Hover: the path from the core lights up (no
	   dimming, cheap). Select: the rest recedes, the ancestors keep their names (.lbl.trail),
	   the first unlit ancestor is ringed. */
	.flow :global(.svelte-flow__edge.trace .svelte-flow__edge-path) {
		stroke: color-mix(in srgb, var(--line-hi) 80%, var(--fg));
		stroke-width: max(2.5px, calc(1.6px / var(--zoom, 1)));
	}
	.flow :global(.svelte-flow__edge.grown.trace .svelte-flow__edge-path) {
		stroke: color-mix(in srgb, var(--ok) 65%, var(--fg));
		stroke-width: max(4px, calc(2.4px / var(--zoom, 1)));
	}
	.flow :global(.svelte-flow__edge.front.trace .svelte-flow__edge-path) {
		stroke: color-mix(in srgb, var(--warn) 75%, var(--fg));
		stroke-width: max(3px, calc(2px / var(--zoom, 1)));
	}
	.flow :global(.svelte-flow__node.trace) {
		--frame: color-mix(in srgb, var(--node) 55%, var(--fg));
	}
	.flow :global(.svelte-flow__node.trace-blocker) {
		box-shadow:
			0 0 0 4px var(--bg),
			0 0 0 5.5px var(--fg);
	}
	.flow.tracing :global(.svelte-flow__edge:not(.trace)) {
		opacity: 0.22;
	}
	.flow.tracing :global(.svelte-flow__node:not(.trace):not(.selected):not(.trace-blocker)) {
		opacity: 0.3;
	}
	.flow.tracing .lbl:not(.trail):not(.pinned) {
		opacity: 0.4;
	}
	.flow :global(.svelte-flow__edge),
	.flow :global(.svelte-flow__node.skill),
	.flow .lbl {
		transition: opacity 160ms ease-out;
	}

	/* Evolution — the tree grows, rows ship, sprout and wither. All one-shot; the view removes
	   the class afterwards (FX_MS). Nothing here runs under prefers-reduced-motion. Needs
	   path[pathLength="1"] and --grow on the node wrapper and on the edge path. */
	@keyframes st-draw {
		from {
			stroke-dashoffset: 1;
		}
		to {
			stroke-dashoffset: 0;
		}
	}
	@keyframes st-fade {
		from {
			opacity: 0;
		}
	}
	@keyframes st-ignite {
		0% {
			opacity: 0;
			transform: scale(0.3);
		}
		60% {
			opacity: 1;
			transform: scale(1.3);
		}
		100% {
			transform: scale(1);
		}
	}
	@keyframes st-burst {
		0% {
			transform: scale(0.8);
			opacity: 1;
		}
		100% {
			transform: scale(3.2);
			opacity: 0;
		}
	}
	@keyframes st-flash {
		0% {
			filter: brightness(2.4) saturate(1.4);
		}
		100% {
			filter: none;
		}
	}
	@keyframes st-sprout {
		0% {
			opacity: 0;
			transform: scale(0);
		}
		70% {
			opacity: 1;
			transform: scale(1.35);
		}
		100% {
			transform: scale(1);
		}
	}
	@keyframes st-wither {
		to {
			opacity: 0;
			transform: scale(0.4);
		}
	}
	@media (prefers-reduced-motion: no-preference) {
		/* Grow: the guides and unlit links fade in, then the lit path draws from the core outward,
		   one BFS step every 160ms, each gem igniting as its link arrives. Labels come last. */
		.flow.fx-grow .guides {
			animation: st-fade 500ms ease-out both;
		}
		.flow.fx-grow :global(.svelte-flow__edge:not(.grown) .svelte-flow__edge-path) {
			animation: st-fade 500ms ease-out both;
			animation-delay: calc(var(--grow, 0) * 160ms + 200ms);
		}
		.flow.fx-grow :global(.svelte-flow__edge.grown .svelte-flow__edge-path) {
			stroke-dasharray: 1 1;
			animation: st-draw 700ms cubic-bezier(0.3, 0.7, 0.4, 1) both;
			animation-delay: calc(var(--grow, 0) * 160ms - 160ms);
		}
		.flow.fx-grow :global(.svelte-flow__node.skill .gem) {
			animation: st-ignite 520ms ease-out both;
			animation-delay: calc(var(--grow, 0) * 160ms + 300ms);
		}
		.flow.fx-grow .labels {
			animation: st-fade 700ms ease-out both;
			animation-delay: 1.6s;
		}
		/* A row just shipped: its link draws in, the gem flashes, one cyan ring bursts. */
		.flow :global(.svelte-flow__edge.fx-ignite .svelte-flow__edge-path) {
			stroke-dasharray: 1 1;
			animation: st-draw 900ms cubic-bezier(0.3, 0.7, 0.4, 1) both;
		}
		.flow :global(.svelte-flow__node.fx-ignite .gem) {
			animation: st-flash 1.4s ease-out both;
		}
		.flow :global(.svelte-flow__node.fx-ignite::after) {
			content: '';
			position: absolute;
			inset: -4px;
			border-radius: 50%;
			border: 2px solid var(--ok);
			pointer-events: none;
			animation: st-burst 1.4s ease-out both;
		}
		/* A new row: the gem grows out of its socket. A state change: a short flash. */
		.flow :global(.svelte-flow__node.fx-sprout .gem) {
			animation: st-sprout 900ms cubic-bezier(0.2, 1.4, 0.4, 1) both;
		}
		.flow :global(.svelte-flow__node.fx-shift .gem) {
			animation: st-flash 900ms ease-out both;
		}
		/* A row removed from the roadmap: its ghost shrinks away before it leaves the DOM. */
		.flow :global(.svelte-flow__node.fx-wither .gem) {
			animation: st-wither 900ms ease-in both;
		}
	}

	/* Legend — a glass panel; each chip is a miniature of the gem it names. */
	.legend {
		position: absolute;
		left: 0.6rem;
		bottom: 0.6rem;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem 0.75rem;
		max-width: 60%;
		padding: 0.45rem 0.65rem;
		background: var(--glass);
		backdrop-filter: var(--glass-filter);
		-webkit-backdrop-filter: var(--glass-filter);
		border: 1px solid var(--glass-brd);
		border-radius: 10px;
		font-size: 0.72rem;
		z-index: 6;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		color: var(--muted);
	}
	.sep {
		width: 1px;
		height: 0.9rem;
		background: var(--glass-brd);
	}
	.dot,
	.gem-sm {
		--node: var(--line-hi);
		--node-core: color-mix(in srgb, var(--node) 20%, var(--bg));
		--frame: color-mix(in srgb, var(--line-hi) 60%, var(--bg));
		width: 10px;
		height: 10px;
		border-radius: 50%;
		display: inline-block;
		box-sizing: border-box;
		flex: 0 0 auto;
		background: var(--node-core);
		box-shadow:
			0 0 0 1.5px var(--bg),
			0 0 0 2.5px var(--frame);
	}
	.dot.st-shipped,
	.dot.st-allocated,
	.dot.st-frontier.spec-ready {
		--frame: color-mix(in srgb, var(--node) 70%, var(--fg));
		background: radial-gradient(
			circle at 36% 30%,
			color-mix(in srgb, var(--node) 50%, var(--fg)) 0,
			var(--node) 42%,
			color-mix(in srgb, var(--node) 55%, var(--bg)) 100%
		);
	}
	.dot.st-shipped {
		--node: var(--ok);
	}
	.dot.st-allocated {
		--node: var(--info);
		background:
			radial-gradient(
				circle closest-side,
				color-mix(in srgb, var(--fg) 88%, var(--node)) 0 22%,
				transparent 34%
			),
			var(--node);
	}
	.dot.st-frontier,
	.dot.st-doing {
		--node: var(--warn);
	}
	.dot.st-frontier.spec-ready {
		--frame: var(--warn);
		box-shadow:
			0 0 0 1.5px var(--bg),
			0 0 0 2.5px var(--frame),
			0 0 8px 2px color-mix(in srgb, var(--warn) 50%, transparent);
	}
	.dot.st-frontier.spec-needed {
		background:
			radial-gradient(circle closest-side, var(--node-core) 0 64%, transparent 66%),
			conic-gradient(from 40deg, var(--node) 0 280deg, transparent 0);
	}
	.dot.st-doing {
		--frame: var(--warn);
		background: linear-gradient(to top, var(--node) 0 50%, var(--node-core) 50%);
	}
	.dot.st-review {
		--node: var(--data-4);
		--frame: color-mix(in srgb, var(--node) 55%, var(--line-hi));
		background: radial-gradient(
			circle closest-side,
			var(--node) 0 30%,
			var(--node-core) 36% 60%,
			var(--node) 66%
		);
	}
	.dot.st-blocked {
		opacity: 0.5;
	}
	.dot.st-milestone {
		--node: var(--fg);
		border-radius: 2px;
		transform: rotate(45deg);
		box-shadow:
			inset 0 0 0 1.5px var(--node),
			inset 0 0 0 3px var(--node-core),
			inset 0 0 0 5px color-mix(in srgb, var(--node) 75%, transparent);
	}
	.dot.st-ungrown {
		--node: var(--bad);
		background: radial-gradient(circle closest-side, var(--bad-soft) 0 58%, var(--node) 64%);
		box-shadow: none;
	}
	.dot.st-dormant {
		--node: var(--ink-faint);
		background: var(--ink-faint);
		box-shadow: none;
		transform: scale(0.7);
	}
	.gem-sm.hex {
		--node: var(--ok);
		width: 13px;
		height: 13px;
		border-radius: 0;
		clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
		background: linear-gradient(
			160deg,
			color-mix(in srgb, var(--node) 50%, var(--fg)),
			var(--node) 45%,
			color-mix(in srgb, var(--node) 45%, var(--bg))
		);
		box-shadow: none;
	}
	.gem-sm.epic {
		--node: var(--fg);
		--frame: var(--muted);
		width: 11px;
		height: 11px;
		background: var(--node-core);
		box-shadow:
			0 0 0 1.5px var(--bg),
			0 0 0 2.5px var(--frame),
			0 0 0 3.5px var(--bg),
			0 0 0 4.5px color-mix(in srgb, var(--frame) 50%, transparent);
	}
	.gem-sm.leaf {
		--frame: var(--muted);
		width: 7px;
		height: 7px;
	}
	.gem-sm.stone {
		--node: var(--fg);
		width: 9px;
		height: 9px;
		border-radius: 1px;
		transform: rotate(45deg);
		background: var(--node-core);
		box-shadow:
			inset 0 0 0 1.5px var(--node),
			inset 0 0 0 3px var(--node-core),
			inset 0 0 0 5px color-mix(in srgb, var(--node) 75%, transparent);
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
