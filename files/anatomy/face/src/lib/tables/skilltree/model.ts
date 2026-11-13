/** The snapshot: a roadmap DataTable shaped into the skill tree's render model — nodes with a
 *  rank, state and position; parent links classed grown / front / plain; one label seed per
 *  gem; the guides' geometry. Pure, so the view only maps it onto Svelte Flow and the
 *  evolution diff can compare two of them. */
import type { DataTableRow } from '$lib/contracts';
import {
	frontierStates,
	gemRank,
	skillTreeLayout,
	GEM_SIZE,
	ORGAN_RING,
	type TreeLayout,
	type TreeState,
	type TreeStateInfo
} from '../planner';
import { rimPoint, sectorReach, DEFAULT_GUIDES } from './guides';
import {
	CORE_ID,
	type EdgeClass,
	type LabelSeed,
	type Spec,
	type TreeEdge,
	type TreeNode
} from './types';

export interface Snapshot extends TreeLayout {
	/** Every placed row, the core first. */
	nodes: TreeNode[];
	edges: TreeEdge[];
	/** One label seed per gem (the core, then the rows); rim names come from rimSeeds(). */
	seeds: LabelSeed[];
	/** Per slug, the frontier rule's verdict (the detail panel reads it). */
	states: Map<string, TreeStateInfo>;
	/** row id → slug and back (the write path and the detail panel speak slug). */
	slugOf: Map<string, string>;
}

const text = (v: unknown): string => (v == null ? '' : String(v));
const LIVE = new Set<TreeState>(['frontier', 'doing', 'review', 'allocated']); // the leaves worth a label first
const apex = new Map(ORGAN_RING.map((r) => [r.key, r]));

export const specOf = (info: TreeStateInfo | undefined): Spec =>
	info?.ready === undefined ? '' : info.ready ? 'spec-ready' : 'spec-needed';

export const CORE_NODE: TreeNode = {
	id: CORE_ID,
	x: 0,
	y: 0,
	size: GEM_SIZE.core,
	rank: 'core',
	state: 'shipped',
	spec: '',
	title: 'core — the shipped estate',
	system: '',
	depth: -1,
	dormant: false
};

/** The FULL board (positions do not jump when a filter changes); `dormant` marks the rows the
 *  "hide queued" toggle hides. `prevAngles` carries the last layout's sector angles, so a
 *  refresh keeps the wedges still unless the counts really moved (hysteresis). */
export function buildSnapshot(
	rows: readonly DataTableRow[],
	prevAngles: Record<string, number> | null = null
): Snapshot {
	const states = frontierStates(rows);
	const lay = skillTreeLayout(rows, ORGAN_RING, prevAngles);
	const ring = new Set(ORGAN_RING.map((r) => r.key));
	const nodes: TreeNode[] = [CORE_NODE];
	const seeds: LabelSeed[] = [
		{ id: CORE_ID, cx: 0, cy: 0, size: GEM_SIZE.core, text: 'core', priority: 1, cls: 'rank-core' }
	];
	const slugOf = new Map<string, string>();
	const bySlug = new Map<string, string>();
	for (const r of rows) {
		const pos = lay.positions.get(r.id);
		if (!pos) continue;
		const slug = text(r.slug);
		slugOf.set(r.id, slug);
		bySlug.set(slug, r.id);
		const info = states.get(slug);
		const state = info?.state ?? 'dormant';
		const sys = apex.get(slug);
		const rank = gemRank(slug, info, ring);
		nodes.push({
			id: r.id,
			x: pos.x,
			y: pos.y,
			size: GEM_SIZE[rank],
			rank,
			state,
			spec: specOf(info),
			title: sys ? `${sys.title} — ${sys.tells}` : text(r.title) || slug,
			system: info?.system ?? '',
			depth: info?.depth ?? -1,
			dormant: state === 'dormant' && !sys
		});
		const priority =
			rank === 'system'
				? 1
				: rank === 'epic'
					? 2
					: rank === 'halo' || state === 'dormant' || state === 'blocked'
						? 5
						: LIVE.has(state)
							? 3
							: 4;
		seeds.push({
			id: r.id,
			cx: pos.x,
			cy: pos.y,
			size: GEM_SIZE[rank],
			text: (sys ? sys.title : '') || text(r.title) || slug || r.id,
			priority,
			cls: `rank-${rank} st-${state}`
		});
	}
	const stateOf = new Map(nodes.map((n) => [n.id, n.state]));
	const edges: TreeEdge[] = [];
	for (const r of rows) {
		if (!lay.positions.has(r.id)) continue;
		const slug = text(r.slug);
		const source = ring.has(slug) ? CORE_ID : bySlug.get(text(r.parent));
		if (!source) continue;
		const s = stateOf.get(r.id);
		const cls: EdgeClass =
			s === 'shipped' || s === 'allocated' ? 'grown' : s === 'frontier' ? 'front' : '';
		edges.push({ source, target: r.id, cls });
	}
	return { ...lay, nodes, edges, seeds, states, slugOf };
}

/** The 13 region names, each at its petal's edge (the design package, spec 04 section 2), for the rows now visible. */
export function rimSeeds(
	snap: Pick<Snapshot, 'nodes' | 'sectors' | 'rings' | 'orbit'>,
	visible: (n: TreeNode) => boolean
): { seeds: LabelSeed[]; reach: Map<string, number> } {
	const rows = snap.nodes.slice(1);
	const reach = sectorReach(rows, snap.sectors, snap.rings[1], visible);
	const opt = { ...DEFAULT_GUIDES, rimMin: snap.rings[2] ?? snap.rings[1] };
	const seeds = snap.sectors.map((s) => {
		const p = rimPoint(s, rows, reach, snap.orbit, visible, opt);
		return {
			id: `__rim__${s.key}`,
			cx: p.x,
			cy: p.y,
			size: 0,
			text: apex.get(s.key)?.title ?? s.key,
			priority: 0,
			cls: 'rim'
		};
	});
	return { seeds, reach };
}
