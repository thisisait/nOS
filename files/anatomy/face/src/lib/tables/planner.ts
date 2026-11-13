/** planner.ts — shape a roadmap DataTable into a graph (dtt-routing-address /
 *  face-planner). PURE and framework-free: it emits plain node/edge records
 *  (structurally an @xyflow/svelte Node/Edge) so the logic is unit-testable in
 *  node, and the Svelte Flow component is just the renderer over these props.
 *
 *  The roadmap's own convention (mirrors $lib/tables/view.ts): a row's `parent`
 *  cell holds its parent's SLUG; an empty/absent parent is a root. Rows carry a
 *  stable `id` (the BFF's withStableIds) — edges reference ids, layout is keyed
 *  on ids, never on the churny slug.
 *
 *  Layout is deliberately simple and DETERMINISTIC (so it is testable and a
 *  re-render doesn't jump): one column per ORGAN SYSTEM (the row's ring-1
 *  ancestor, in ring order; "outside the ring" last), rows stacked within a
 *  column ordered by depth then slug, x indented by depth so hierarchy reads at
 *  a glance. The skill tree (skillTreeLayout below) is the radial reading.
 */
import type { DataTable, DataTableRow } from '$lib/contracts';
import organRing from './organ-ring.json';

export interface PlannerNode {
	id: string;
	position: { x: number; y: number };
	data: {
		label: string;
		slug: string;
		status: string;
		kind: string; // release | epic | feature | task | fee | weakness | decision
		track: string;
		group: string; // the column: the row's organ system, or OUTSIDE_RING
		orphanParent?: string; // set when `parent` names a slug no row provides
	};
}

export interface PlannerEdge {
	id: string;
	source: string;
	target: string;
}

export interface PlannerGraph {
	nodes: PlannerNode[];
	edges: PlannerEdge[];
	/** parent slugs referenced by a row but present on no row — surfaced, not
	 *  swallowed (an edge to nothing is exactly the kind of silent gap the estate
	 *  refuses; the view can badge these). */
	danglingParents: string[];
}

/** The minimal row payload for a reparent write (slice 2, interactive edit).
 *  Keyed on the child's SLUG; the human door merges, so only the changed cell
 *  travels — status/verified (table-owned) are never touched. `parentId` null
 *  or '' un-parents (sets the row to a root). */
export interface ReparentPayload {
	slug: string;
	parent: string;
}

/** Build a reparent write, or throw with a caller-facing reason. REFUSES the
 *  writes that would corrupt the tree — self-parent, and parenting a node under
 *  one of its own descendants (a cycle). The graph's whole legibility rests on
 *  it staying a forest, so this is a hard guard, not a warning. */
export function reparentPayload(
	table: DataTable | null | undefined,
	childId: string,
	parentId: string | null
): ReparentPayload {
	const rows = (table?.rows ?? []).filter((r) => typeof r.id === 'string' && r.id);
	const byId = new Map(rows.map((r) => [r.id, r]));
	const child = byId.get(childId);
	if (!child) throw new Error('unknown row to reparent');
	const childSlug = cell(child, 'slug');
	if (!childSlug) throw new Error('row has no slug — cannot address it for a write');

	if (!parentId) return { slug: childSlug, parent: '' }; // un-parent → root

	if (parentId === childId) throw new Error('a row cannot be its own parent');
	const parent = byId.get(parentId);
	if (!parent) throw new Error('unknown parent row');
	const parentSlug = cell(parent, 'slug');
	if (!parentSlug) throw new Error('parent row has no slug');

	// Cycle guard: walk the proposed parent's ancestry; if the child appears, the
	// edge would close a loop. bySlug for the walk (parent cells hold slugs).
	const bySlug = new Map(rows.map((r) => [cell(r, 'slug'), r] as const));
	let cur: DataTableRow | undefined = parent;
	const seen = new Set<string>();
	while (cur) {
		if (cur.id === childId)
			throw new Error('that would parent a row under its own descendant (a cycle)');
		const p = cell(cur, 'parent');
		if (!p || seen.has(p)) break;
		seen.add(p);
		cur = bySlug.get(p);
	}
	return { slug: childSlug, parent: parentSlug };
}

const COL_W = 320; // horizontal gap between organ-system columns
const ROW_H = 84; // vertical gap between stacked rows
const INDENT = 26; // x nudge per depth level, so children sit right of parents

function cell(row: DataTableRow, key: string): string {
	const v = row[key];
	return typeof v === 'string' ? v : v == null ? '' : String(v);
}

/** Depth of a row by walking `parent` slugs; cycle-safe (caps at the row count). */
function depthOf(row: DataTableRow, bySlug: Map<string, DataTableRow>, max: number): number {
	let d = 0;
	let cur = row;
	const seen = new Set<string>();
	while (d <= max) {
		const p = cell(cur, 'parent');
		if (!p) return d;
		const parent = bySlug.get(p);
		if (!parent || seen.has(p)) return d; // orphan or cycle → treat as reached
		seen.add(p);
		cur = parent;
		d++;
	}
	return d;
}

export const OUTSIDE_RING = 'outside the ring';

/** Turn a roadmap-shaped DataTable into a graph. Rows with no `id` are skipped
 *  (the BFF guarantees ids; a row without one cannot be an edge endpoint).
 *  `states` (frontierStates of the FULL board) names each row's organ system;
 *  pass it when `table` is filtered, or a hidden shipped ancestor drops a row
 *  out of its system's column. */
export function rowsToGraph(
	table: DataTable | null | undefined,
	states: Map<string, TreeStateInfo> = frontierStates(table?.rows ?? [])
): PlannerGraph {
	const rows = (table?.rows ?? []).filter((r) => typeof r.id === 'string' && r.id);
	const bySlug = new Map<string, DataTableRow>();
	for (const r of rows) {
		const s = cell(r, 'slug');
		if (s) bySlug.set(s, r);
	}

	// Column per organ system in ring order, "outside the ring" last.
	const groupOf = (r: DataTableRow) => states.get(cell(r, 'slug'))?.system || OUTSIDE_RING;
	const rank = new Map<string, number>(ORGAN_RING.map((r, i) => [r.key, i]));
	const groups = [...new Set(rows.map(groupOf))].sort(
		(a, b) => (rank.get(a) ?? Infinity) - (rank.get(b) ?? Infinity)
	);
	const groupX = new Map(groups.map((t, i) => [t, i * COL_W]));
	const depth = new Map(rows.map((r) => [r.id, depthOf(r, bySlug, rows.length)]));

	// Order rows within each column by (depth, slug) for a stable stack.
	const perGroupCount = new Map<string, number>();
	const nodes: PlannerNode[] = [];
	const dangling = new Set<string>();

	const ordered = [...rows].sort((a, b) => {
		const ga = groupX.get(groupOf(a))!;
		const gb = groupX.get(groupOf(b))!;
		if (ga !== gb) return ga - gb;
		const da = depth.get(a.id) ?? 0;
		const db = depth.get(b.id) ?? 0;
		if (da !== db) return da - db;
		return cell(a, 'slug') < cell(b, 'slug') ? -1 : 1;
	});

	for (const r of ordered) {
		const group = groupOf(r);
		const track = cell(r, 'track') || 'untracked';
		const d = depth.get(r.id) ?? 0;
		const n = perGroupCount.get(group) ?? 0;
		perGroupCount.set(group, n + 1);
		const parentSlug = cell(r, 'parent');
		const orphan = parentSlug && !bySlug.has(parentSlug) ? parentSlug : undefined;
		if (orphan) dangling.add(orphan);
		nodes.push({
			id: r.id,
			position: { x: (groupX.get(group) ?? 0) + d * INDENT, y: n * ROW_H },
			data: {
				label: cell(r, 'title') || cell(r, 'slug') || r.id,
				slug: cell(r, 'slug'),
				status: cell(r, 'status'),
				kind: cell(r, 'kind'),
				track,
				group,
				...(orphan ? { orphanParent: orphan } : {})
			}
		});
	}

	// Edges: parent-slug → this row. Skip when the parent slug names no row.
	const edges: PlannerEdge[] = [];
	for (const r of rows) {
		const p = cell(r, 'parent');
		if (!p) continue;
		const parent = bySlug.get(p);
		if (!parent) continue; // dangling — recorded above, no edge to nothing
		edges.push({ id: `${parent.id}->${r.id}`, source: parent.id, target: r.id });
	}

	return { nodes, edges, danglingParents: [...dangling].sort() };
}

// ── The passive tree (face-skill-tree-view; operator 2026-11-13, roadmap-organic-structure) ──

/** Ring 1: the 13 apex organ systems in ring order (core column, left wing, right wing),
 *  generated from files/anatomy/apex/ruling.yml by tools/organ-ring-gen.py. */
export const ORGAN_RING: readonly { key: string; side: string }[] = organRing.ring;

/** Mirrors tools/roadmap-status.py: OPEN statuses can be built; GROWN ones open the frontier. */
const OPEN = new Set(['active', 'next']);
const GROWN = new Set(['shipped', 'active']);

export type TreeState =
	| 'shipped'
	| 'allocated' // active, every ancestor grown
	| 'frontier' // next, every ancestor grown: buildable
	| 'blocked' // open, under an ungrown ancestor (blockedBy names the nearest)
	| 'review'
	| 'doing'
	| 'milestone' // rel-* outside the ring
	| 'ungrown' // open, hangs under no organ system
	| 'dormant'; // queued, parked, dropped, inbox, …

export interface TreeStateInfo {
	state: TreeState;
	system: string; // ring-1 ancestor slug; '' outside the ring
	depth: number; // 0 = the system itself; -1 outside the ring
	blockedBy?: string;
	blockedByStatus?: string;
}

function byStatus(status: string): TreeState {
	if (status === 'active') return 'allocated';
	if (status === 'next') return 'frontier';
	if (status === 'shipped' || status === 'review' || status === 'doing') return status;
	return 'dormant';
}

function isMilestone(r: DataTableRow): boolean {
	return cell(r, 'slug').startsWith('rel-') || cell(r, 'kind') === 'release';
}

/** Per slug, the state `tools/roadmap-status.py --frontier ring` gives it: its `frontier`
 *  list = allocated + frontier here, its `blocked` list = blocked. Outside the ring an open
 *  row is ungrown (Python names only the top-level ones), a rel-* row a milestone. */
export function frontierStates(
	rows: readonly DataTableRow[],
	ring: readonly string[] = ORGAN_RING.map((r) => r.key)
): Map<string, TreeStateInfo> {
	const bySlug = new Map<string, DataTableRow>();
	const kids = new Map<string, DataTableRow[]>();
	for (const r of rows) {
		const s = cell(r, 'slug');
		if (!s) continue;
		bySlug.set(s, r);
		// A ring system hung under another system is still its own root (the layout pins it on
		// ring 1): never walk it as a child, or its subtree is labelled with the wrong system.
		if (ring.includes(s)) continue;
		const p = cell(r, 'parent');
		if (!kids.has(p)) kids.set(p, []);
		kids.get(p)!.push(r);
	}
	const out = new Map<string, TreeStateInfo>();
	for (const root of ring) {
		const rootRow = bySlug.get(root);
		if (!rootRow || out.has(root)) continue;
		out.set(root, { state: byStatus(cell(rootRow, 'status')), system: root, depth: 0 });
		const stack: [DataTableRow, number, DataTableRow | null][] = [[rootRow, 0, null]];
		while (stack.length) {
			const [node, depth, blocker] = stack.pop()!;
			const here = GROWN.has(cell(node, 'status')) ? blocker : node;
			for (const c of kids.get(cell(node, 'slug')) ?? []) {
				const slug = cell(c, 'slug');
				if (out.has(slug)) continue; // a cycle, or a system hung under another
				const status = cell(c, 'status');
				const info: TreeStateInfo = { state: byStatus(status), system: root, depth: depth + 1 };
				if (OPEN.has(status) && here) {
					info.state = 'blocked';
					info.blockedBy = cell(here, 'slug');
					info.blockedByStatus = cell(here, 'status');
				}
				out.set(slug, info);
				stack.push([c, depth + 1, here]);
			}
		}
	}
	for (const [slug, r] of bySlug) {
		if (out.has(slug)) continue;
		const status = cell(r, 'status');
		const state = isMilestone(r) ? 'milestone' : OPEN.has(status) ? 'ungrown' : byStatus(status);
		out.set(slug, { state, system: '', depth: -1 });
	}
	return out;
}

export interface TreeLayout {
	/** row id → position; the core sits at (0, 0). */
	positions: Map<string, { x: number; y: number }>;
	/** ring keys with no row on the board: the ring is incomplete, say so. */
	absent: string[];
}

const R1 = 360; // ring-1 radius
const RING_GAP = 190; // minimum step between rings
const MIN_ARC = 48; // minimum arc between neighbours on one ring (a dot + its label)
const BAND_GAP = 240; // the outside-the-ring band sits this far below the tree
const BAND_COL = 200;
const BAND_ROW = 70;
const BAND_COLS = 12;

/** Radial placement: the systems on ring 1, the core column's arc centred at the top, the
 *  left wing down the left, the right wing down the right. A system's sector is proportional
 *  to its subtree size; a node's children split its sector by their subtree sizes, sorted by
 *  slug. Each deeper ring's radius grows until its closest neighbours sit MIN_ARC apart.
 *  Rows outside the ring go to a band under the tree: milestones first, then by slug. */
export function skillTreeLayout(
	rows: readonly DataTableRow[],
	ring: readonly { key: string; side: string }[] = ORGAN_RING
): TreeLayout {
	const withId = rows.filter((r) => typeof r.id === 'string' && r.id);
	const bySlug = new Map(withId.map((r) => [cell(r, 'slug'), r] as const));
	const ringKeys = new Set(ring.map((r) => r.key));
	const kids = new Map<string, DataTableRow[]>();
	for (const r of withId) {
		if (ringKeys.has(cell(r, 'slug'))) continue; // a system is always on ring 1
		const p = cell(r, 'parent');
		if (!kids.has(p)) kids.set(p, []);
		kids.get(p)!.push(r);
	}
	for (const list of kids.values())
		list.sort((a, b) => (cell(a, 'slug') < cell(b, 'slug') ? -1 : 1));

	const absent = ring.map((r) => r.key).filter((k) => !bySlug.has(k));
	const side = (s: string) =>
		ring.filter((r) => r.side === s && bySlug.has(r.key)).map((r) => r.key);
	// Clockwise from the bottom (screen y grows down): left wing up, core over the top, right wing down.
	const core = side('core');
	const seq = [...side('left').reverse(), ...core, ...side('right')];

	// Subtree sizes; `weight` doubles as the visited set, so a cycle is never entered.
	const weight = new Map<string, number>();
	const weigh = (s: string): number => {
		weight.set(s, 1);
		let w = 1;
		for (const c of kids.get(s) ?? [])
			if (!weight.has(cell(c, 'slug'))) w += weigh(cell(c, 'slug'));
		weight.set(s, w);
		return w;
	};
	const total = seq.reduce((n, k) => n + weigh(k), 0) || 1;

	// Angles first (they do not depend on the radius), then one radius per depth.
	const angle = new Map<string, number>();
	const depth = new Map<string, number>();
	const place = (s: string, a: number, b: number, d: number) => {
		angle.set(s, (a + b) / 2);
		depth.set(s, d);
		const children = (kids.get(s) ?? [])
			.map((c) => cell(c, 'slug'))
			.filter((c) => weight.has(c) && !angle.has(c));
		const sum = children.reduce((n, c) => n + weight.get(c)!, 0);
		let at = a;
		for (const c of children) {
			const span = ((b - a) * weight.get(c)!) / sum;
			place(c, at, at + span, d + 1);
			at += span;
		}
	};
	const sector = new Map<string, [number, number]>();
	let at = 0;
	for (const k of seq) {
		const span = (2 * Math.PI * weight.get(k)!) / total;
		sector.set(k, [at, at + span]);
		at += span;
	}
	const shift = core.length
		? -Math.PI / 2 - (sector.get(core[0])![0] + sector.get(core[core.length - 1])![1]) / 2
		: Math.PI / 2;
	for (const k of seq) place(k, sector.get(k)![0] + shift, sector.get(k)![1] + shift, 1);

	const radius = [0, R1];
	const maxDepth = Math.max(1, ...depth.values());
	for (let d = 2; d <= maxDepth; d++) {
		const as = [...depth].filter(([, v]) => v === d).map(([s]) => angle.get(s)!);
		as.sort((x, y) => x - y);
		let gap = Infinity;
		for (let i = 1; i < as.length; i++) gap = Math.min(gap, as[i] - as[i - 1]);
		radius[d] = Math.max(radius[d - 1] + RING_GAP, gap > 0 && gap < Infinity ? MIN_ARC / gap : 0);
	}

	const positions = new Map<string, { x: number; y: number }>();
	for (const r of withId) {
		const s = cell(r, 'slug');
		const a = angle.get(s);
		if (a === undefined) continue;
		const rad = radius[depth.get(s)!];
		positions.set(r.id, { x: Math.round(rad * Math.cos(a)), y: Math.round(rad * Math.sin(a)) });
	}
	const outside = withId
		.filter((r) => !positions.has(r.id))
		.sort(
			(a, b) =>
				Number(isMilestone(b)) - Number(isMilestone(a)) ||
				(cell(a, 'slug') < cell(b, 'slug') ? -1 : 1)
		);
	const top = radius[maxDepth] + BAND_GAP;
	const left = (-(Math.min(outside.length, BAND_COLS) - 1) * BAND_COL) / 2;
	outside.forEach((r, i) =>
		positions.set(r.id, {
			x: Math.round(left + (i % BAND_COLS) * BAND_COL),
			y: Math.round(top + Math.floor(i / BAND_COLS) * BAND_ROW)
		})
	);
	return { positions, absent };
}
