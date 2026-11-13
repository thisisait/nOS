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
import { sectorAngles, stableAngles } from './skilltree/guides';

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
export const ORGAN_RING: readonly { key: string; side: string; title: string; tells: string }[] =
	organRing.ring;

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
	/** on a buildable row (allocated, frontier): does its body carry a ready spec? */
	ready?: boolean;
	missing?: SpecPart[];
}

// The same markers as spec_ready() in tools/roadmap-status.py (operator 2026-11-13: the loop
// builds only a frontier row with a READY SPEC). Change both together.
const LABEL = String.raw`(?:\s*\([^)\n]*\))?\s*:`;
const SPEC_STAMP = /spec (?:accepted|ready)|explore rounds? \d/i;
const SPEC_PARTS = {
	goal: new RegExp(String.raw`\bgoal${LABEL}|^#+ *goal\b`, 'im'),
	slice: new RegExp(
		String.raw`smallest(?: shippable)? slice|first slice|\bslices?(?: \d+)?${LABEL}|\bslice \d|^#{1,6} [^\n]*\bslice`,
		'im'
	),
	e2e: new RegExp(
		String.raw`\be2e(?: acceptance)?${LABEL}|\bacceptance${LABEL}|^#{1,6} [^\n]*\b(?:e2e|acceptance)\b`,
		'im'
	),
	'must-not': new RegExp(
		String.raw`\bmust not${LABEL}|^#+ *must not\b|\bout of scope${LABEL}|\bnon-goals?${LABEL}`,
		'im'
	)
};
export type SpecPart = keyof typeof SPEC_PARTS;

/** Ready = the top agent's stamp (SPEC ACCEPTED / SPEC READY / explore round N), or a label or
 *  heading for each of the four parts: goal, smallest slice, e2e acceptance, must not. */
export function specReady(body: unknown): { ready: boolean; missing: SpecPart[] } {
	const text = body == null ? '' : String(body);
	if (SPEC_STAMP.test(text)) return { ready: true, missing: [] };
	const missing = (Object.keys(SPEC_PARTS) as SpecPart[]).filter((k) => !SPEC_PARTS[k].test(text));
	return { ready: missing.length === 0, missing };
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
				} else if (OPEN.has(status)) Object.assign(info, specReady(c.body));
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
	/** row id → the node's CENTRE; the core sits at (0, 0). */
	positions: Map<string, { x: number; y: number }>;
	/** ring keys with no row on the board: the ring is incomplete, say so. */
	absent: string[];
	/** each organ system's wedge, screen radians (y down, −π/2 is straight up). */
	sectors: { key: string; from: number; to: number }[];
	/** tree ring radii by depth: [0, ring 1, ring 2, …]. */
	rings: number[];
	/** the milestone orbit's radius, 0 when the board has none. */
	orbit: number;
	/** the halo's ring radii (rows hung under no system), [] when every row is hung. */
	halo: number[];
	/** each system's wedge in radians, the hysteresis input for the next layout (skill-tree v2). */
	angles: Record<string, number>;
}

const R1 = 340; // ring 1 (the 13 systems); raised only if their labels would not fit
/** Step out to ring d; the last entry repeats. Floored at 120 from ring 3 on (skill-tree v2):
 *  the decaying 100 / 85 crowded the outer rings, where most leaves live. */
const RING_GAP = [0, 0, 150, 120];
const MIN_ARC = [0, 110, 40, 28]; // arc between neighbours on ring d; the last entry repeats
const SUB_RINGS = 5; // a crowded ring splits into up to this many radial sub-rings
const SUB_STEP = 30; // radial distance between sub-rings (> the leaf arc, so dots never touch)
/** Sector weight = rows ^ SECTOR_POWER with a SECTOR_FLOOR_DEG floor (skill-tree v2): linear
 *  weights gave the spine 97.5° for 199 rows and a one-row system 18.5°; the square root
 *  gives 67° and 14°, so no petal is empty and none is crammed. */
const SECTOR_POWER = 0.5;
const SECTOR_FLOOR_DEG = 14;
/** A refresh keeps the previous wedges unless a target moved by more than this fraction. */
const SECTOR_HYSTERESIS = 0.15;
const ORBIT_GAP = 140; // the milestone orbit sits this far beyond the tree
const ORBIT_ARC = 110;
const HALO_GAP = 160; // unhung constellations start this far beyond the orbit
const HALO_ARC = [0, 24, 22]; // a halo root's neighbours; descendants keep the last entry
const HALO_GAP_D = [0, 0, 90, 75];
const last = (xs: readonly number[], i: number) => xs[Math.min(i, xs.length - 1)];

/** Push sorted angles apart until neighbours sit ≥ gap, inside [lo, hi]; order is kept.
 *  Two passes suffice when (n − 1)·gap ≤ hi − lo, which the caller's radius guarantees. */
function spread(as: number[], lo: number, hi: number, gap: number): number[] {
	const out = as.slice();
	if (!out.length) return out;
	out[0] = Math.max(out[0], lo);
	for (let i = 1; i < out.length; i++) out[i] = Math.max(out[i], out[i - 1] + gap);
	out[out.length - 1] = Math.min(out[out.length - 1], hi);
	for (let i = out.length - 2; i >= 0; i--) out[i] = Math.min(out[i], out[i + 1] - gap);
	return out;
}

/** Radial placement: the systems on ring 1, the core column's arc centred at the top, the
 *  left wing down the left, the right wing down the right. A system's wedge weighs
 *  rows^0.5 with a 14° floor, held still between refreshes by hysteresis (`prevAngles`); a
 *  node's children split its wedge by their subtree sizes, sorted by slug (a stable order:
 *  a row changing state never changes place). Ring d's radius is the smallest at which
 *  every system's ring-d rows fit its wedge MIN_ARC apart (then spread to that gap inside
 *  the wedge) and at least RING_GAP beyond ring d−1 — sector-aware packing, so one crowded
 *  system never pushes the whole board out. Milestones orbit beyond the tree, centred at
 *  the top; rows hung under no system form a dim halo of their own constellations outside. */
export function skillTreeLayout(
	rows: readonly DataTableRow[],
	ring: readonly { key: string; side: string }[] = ORGAN_RING,
	prevAngles: Record<string, number> | null = null
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

	const angle = new Map<string, number>();
	const depth = new Map<string, number>();
	const radius = new Map<string, number>();

	/** One constellation set. Wedged (the tree): `roots` own wedges ∝ weight, floored so
	 *  `arcs[1]` fits on `r1`, and every ring is packed per wedge. Laned (the halo): one lane
	 *  round the whole circle, every ring packed as a whole — the roots are many and bare, so
	 *  wedges would starve the few big constellations. Descendants ring outward either way. */
	const constellate = (
		roots: string[],
		r1: number,
		gaps: readonly number[],
		arcs: readonly number[],
		centreOn: string[],
		wedged: boolean
	): { rings: number[]; sectors: { key: string; from: number; to: number }[] } => {
		const rings = [0, Math.max(r1, (roots.length * arcs[1]) / (2 * Math.PI))];
		// Wedges ∝ rows^0.5 with a 14° floor; the previous layout's angles hold unless a target
		// drifted > 15 % (hysteresis), so a refresh does not make the petals breathe. The halo
		// (one lane) keeps spans ∝ rows: they only seed its roots' bearings before packing.
		const total = roots.reduce((n, k) => n + weight.get(k)!, 0) || 1;
		const target = wedged
			? sectorAngles(
					Object.fromEntries(roots.map((k) => [k, weight.get(k)!])),
					SECTOR_POWER,
					SECTOR_FLOOR_DEG
				)
			: Object.fromEntries(roots.map((k) => [k, (2 * Math.PI * weight.get(k)!) / total]));
		const span = new Map(
			Object.entries(wedged ? stableAngles(prevAngles, target, SECTOR_HYSTERESIS) : target)
		);
		const sectors: { key: string; from: number; to: number }[] = [];
		let at = 0;
		for (const k of roots) {
			sectors.push({ key: k, from: at, to: at + span.get(k)! });
			at += span.get(k)!;
		}
		// Rotate so the wedges in `centreOn` straddle the top (or the first root starts there).
		const mid = centreOn.length
			? (sectors.find((s) => s.key === centreOn[0])!.from +
					sectors.find((s) => s.key === centreOn[centreOn.length - 1])!.to) /
				2
			: 0;
		const shift = -Math.PI / 2 - mid;
		for (const s of sectors) {
			s.from += shift;
			s.to += shift;
		}
		const lanes = wedged ? sectors : [{ key: '*', from: shift, to: shift + 2 * Math.PI }];
		const lane = new Map<string, string>();
		const place = (s: string, a: number, b: number, d: number, k: string) => {
			angle.set(s, (a + b) / 2);
			depth.set(s, d);
			lane.set(s, k);
			const children = (kids.get(s) ?? [])
				.map((c) => cell(c, 'slug'))
				.filter((c) => weight.has(c) && !angle.has(c));
			const sum = children.reduce((n, c) => n + weight.get(c)!, 0);
			let cur = a;
			for (const c of children) {
				const w = ((b - a) * weight.get(c)!) / sum;
				place(c, cur, cur + w, d + 1, k);
				cur += w;
			}
		};
		for (const s of sectors) place(s.key, s.from, s.to, 1, wedged ? s.key : '*');
		for (const s of sectors) radius.set(s.key, rings[1]);

		// Each ring: group by (depth, lane); a crowded ring splits into up to SUB_RINGS radial
		// sub-rings (members round-robin by angle order), so the ring's radius is the single-ring
		// need ÷ sub-rings; neighbours then sit ≥ arc apart along a sub-ring and ≥ SUB_STEP across.
		const groups = new Map<string, string[]>();
		let maxDepth = 1;
		for (const [s, k] of lane) {
			const d = depth.get(s)!;
			maxDepth = Math.max(maxDepth, d);
			const key = `${d}|${k}`;
			if (!groups.has(key)) groups.set(key, []);
			groups.get(key)!.push(s);
		}
		let prevSub = 1;
		for (let d = wedged ? 2 : 1; d <= maxDepth; d++) {
			const arc = last(arcs, d);
			let single = 0;
			for (const l of lanes) {
				const n = groups.get(`${d}|${l.key}`)?.length ?? 0;
				if (n) single = Math.max(single, (n * arc) / (l.to - l.from));
			}
			const base = d === 1 ? r1 : rings[d - 1] + last(gaps, d);
			const sub = Math.min(SUB_RINGS, Math.max(1, Math.ceil(single / base)));
			const half = ((sub - 1) / 2) * SUB_STEP; // the band's half-width; arcs are kept on its inner edge
			const band = ((prevSub - 1) / 2) * SUB_STEP + half;
			let need = base + (d === 1 ? half : band);
			for (const l of lanes) {
				const n = groups.get(`${d}|${l.key}`)?.length ?? 0; // n−1 gaps of arc/sub + a full arc of margins
				if (n) need = Math.max(need, (((n - 1) / sub + 1) * arc) / (l.to - l.from) + half);
			}
			rings[d] = Math.ceil(need);
			prevSub = sub;
			const gap = arc / (sub * (rings[d] - half));
			const margin = arc / (2 * (rings[d] - half)); // a full arc at a lane border, whatever the sub-ring
			for (const l of lanes) {
				const members = groups.get(`${d}|${l.key}`);
				if (!members) continue;
				members.sort((x, y) => angle.get(x)! - angle.get(y)! || (x < y ? -1 : 1));
				const as = spread(
					members.map((m) => angle.get(m)!),
					l.from + margin,
					l.to - margin,
					gap
				);
				members.forEach((m, i) => {
					angle.set(m, as[i]);
					radius.set(m, rings[d] + ((i % sub) - (sub - 1) / 2) * SUB_STEP);
				});
			}
		}
		return { rings, sectors };
	};

	for (const k of seq) weigh(k);
	const tree = constellate(seq, R1, RING_GAP, MIN_ARC, core, true);

	const positions = new Map<string, { x: number; y: number }>();
	const put = (id: string, rad: number, a: number) =>
		positions.set(id, { x: Math.round(rad * Math.cos(a)), y: Math.round(rad * Math.sin(a)) });
	for (const r of withId) {
		const s = cell(r, 'slug');
		if (angle.has(s)) put(r.id, radius.get(s)!, angle.get(s)!);
	}

	// Milestones: an orbit beyond the tree, by slug clockwise, centred at the top.
	const outer = tree.rings[tree.rings.length - 1];
	const stones = withId
		.filter((r) => !positions.has(r.id) && isMilestone(r))
		.sort((a, b) => (cell(a, 'slug') < cell(b, 'slug') ? -1 : 1));
	const orbit = stones.length ? outer + ORBIT_GAP : 0;
	stones.forEach((r, i) =>
		put(r.id, orbit, -Math.PI / 2 + ((i - (stones.length - 1) / 2) * ORBIT_ARC) / orbit)
	);

	// The halo: every row still unplaced, as constellations rooted on their own top rows. A
	// milestone's children lead, in the orbit's order, and the lane is centred on them, so their
	// edges run straight out from the crown instead of chording across the tree.
	const loose = withId.filter((r) => !positions.has(r.id));
	const looseSlugs = new Set(loose.map((r) => cell(r, 'slug')));
	const stoneSlugs = new Set(stones.map((r) => cell(r, 'slug')));
	const rankOf = (r: DataTableRow) =>
		looseSlugs.has(cell(r, 'parent')) ? 2 : stoneSlugs.has(cell(r, 'parent')) ? 0 : 1;
	const key = (r: DataTableRow) => `${rankOf(r) ? '' : cell(r, 'parent')}\0${cell(r, 'slug')}`;
	const order = [...loose].sort((a, b) => rankOf(a) - rankOf(b) || (key(a) < key(b) ? -1 : 1));
	const haloRoots: string[] = [];
	const underStone: string[] = [];
	for (const r of order) {
		const s = cell(r, 'slug');
		if (weight.has(s)) continue; // reached from an earlier root (or a cycle's other half)
		weigh(s);
		haloRoots.push(s);
		if (rankOf(r) === 0) underStone.push(s);
	}
	let halo: number[] = [];
	if (haloRoots.length) {
		const base = (orbit || outer) + HALO_GAP;
		halo = constellate(haloRoots, base, HALO_GAP_D, HALO_ARC, underStone, false).rings.slice(1);
		for (const r of loose) put(r.id, radius.get(cell(r, 'slug'))!, angle.get(cell(r, 'slug'))!);
	}
	const angles = Object.fromEntries(tree.sectors.map((s) => [s.key, s.to - s.from]));
	return { positions, absent, sectors: tree.sectors, rings: tree.rings, orbit, halo, angles };
}

// ── Labels: the level of detail is a collision pass (operator 2026-11-13: overlapping texts) ──

/** A label candidate: the gem's centre and size in flow px, its text, its priority (0 a sector
 *  name on the rim, 1 core and system, 2 epic and milestone, 3 frontier leaf, 4 leaf, 5 halo).
 *  A rim name has no gem (size 0) and sits at its sector's angle, outside the tree. */
export interface LabelItem {
	id: string;
	cx: number;
	cy: number;
	size: number;
	text: string;
	priority: number;
	/** the view's classes for it: rank and state, or `rim` */
	cls: string;
}

/** A placed label, SCREEN px relative to the flow origin (the view adds the viewport's x, y):
 *  w/h are the box's constant size on screen, x/y its top-left. Text never wraps; a title
 *  longer than the box is cut with an ellipsis by the view (the full one is the tooltip). */
export interface LabelBox extends LabelItem {
	x: number;
	y: number;
	w: number;
	h: number;
}

/** Screen metrics per tier: average glyph width, horizontal padding, max width, height. The
 *  width is an estimate (no canvas in a test) that over-measures, so a pass is a safe pass. */
export const LABEL_PX = {
	big: { char: 7.6, pad: 18, max: 200, h: 22 }, // rim names, core, systems (13px semibold)
	small: { char: 6.4, pad: 16, max: 180, h: 18 } // everything else (11px)
};
const RIM_GAP = 6; // screen px between a gem's rim and its label
/** Zoom at which epics and milestones, then leaves, become label candidates at all. */
export const LABEL_LOD = { mid: 0.45, near: 0.9 };

/** The box for one label at a zoom: anchored on the gem's rim along the branch angle (the ray
 *  from the core), the way PoE hangs a name off a node — outward, so neighbours on a ring
 *  diverge instead of stacking below each other. */
export function labelBox(it: LabelItem, zoom: number): LabelBox {
	const m = it.priority <= 1 ? LABEL_PX.big : LABEL_PX.small;
	const w = Math.min(m.max, it.text.length * m.char + m.pad);
	const h = m.h;
	const len = Math.hypot(it.cx, it.cy);
	const ux = len ? it.cx / len : 0;
	const uy = len ? it.cy / len : 1;
	const g = (it.size / 2) * zoom + RIM_GAP;
	const ax = it.cx * zoom + ux * g;
	const ay = it.cy * zoom + uy * g;
	const x = ax - (ux > 0.35 ? 0 : ux < -0.35 ? w : w / 2);
	const y = ay - (uy > 0.35 ? 0 : uy < -0.35 ? h : h / 2);
	return { ...it, x, y, w, h };
}

const hits = (a: LabelBox, b: { x: number; y: number; w: number; h: number }) =>
	a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** Gem box per rank, flow px (the layout gives centres; Svelte Flow positions a corner). */
export const GEM_SIZE = { core: 56, system: 30, epic: 14, leaf: 10, halo: 8 } as const;
export type GemRank = keyof typeof GEM_SIZE;

export function gemRank(slug: string, info: TreeStateInfo | undefined, ring: Set<string>): GemRank {
	if (ring.has(slug)) return 'system';
	if (!info || info.depth < 0) return info?.state === 'milestone' ? 'epic' : 'halo';
	return info.depth === 1 ? 'epic' : 'leaf';
}

const RIM_NAME_GAP = 16; // flow px beyond the guide rim (rings[last] + 60) where a sector's name sits
const LIVE = new Set<TreeState>(['frontier', 'doing', 'review', 'allocated']); // the leaves worth a label first

/** Every label candidate of a board: the core, one per placed row (a system reads by its apex
 *  name, never its row title, so the 13 names are short and whole), and one rim name per sector
 *  just outside the tree — the PoE class name at the edge of its wedge. `cls` carries the
 *  state and rank classes the view styles by. */
export function skillTreeLabels(
	rows: readonly DataTableRow[],
	lay: TreeLayout,
	states: ReadonlyMap<string, TreeStateInfo>,
	ring: readonly { key: string; title: string }[] = ORGAN_RING
): LabelItem[] {
	const keys = new Set(ring.map((r) => r.key));
	const title = new Map(ring.map((r) => [r.key, r.title]));
	const out: LabelItem[] = [
		{
			id: '__core__',
			cx: 0,
			cy: 0,
			size: GEM_SIZE.core,
			text: 'core',
			priority: 1,
			cls: 'rank-core'
		}
	];
	for (const r of rows) {
		const pos = lay.positions.get(r.id);
		if (!pos) continue;
		const slug = cell(r, 'slug');
		const info = states.get(slug);
		const state = info?.state ?? 'dormant';
		const rank = gemRank(slug, info, keys);
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
		out.push({
			id: r.id,
			cx: pos.x,
			cy: pos.y,
			size: GEM_SIZE[rank],
			text: (keys.has(slug) ? title.get(slug) : '') || cell(r, 'title') || slug || r.id,
			priority,
			cls: `rank-${rank} st-${state}`
		});
	}
	const rim = lay.rings[lay.rings.length - 1] + 60 + RIM_NAME_GAP;
	for (const s of lay.sectors) {
		const a = (s.from + s.to) / 2;
		out.push({
			id: `__rim__${s.key}`,
			cx: rim * Math.cos(a),
			cy: rim * Math.sin(a),
			size: 0,
			text: title.get(s.key) ?? s.key,
			priority: 0,
			cls: 'rim'
		});
	}
	return out;
}

/** Greedy level of detail: candidates by priority (then id, so it is stable), each kept only
 *  if its box clears every kept box and — below the system tier — every gem on screen as big
 *  as its own (an epic's name may lie over leaf dots, never over another epic or a system).
 *  Epics need LABEL_LOD.mid, leaves LABEL_LOD.near; rim names and systems are always
 *  candidates. `always` (hovered, focused, selected) are kept first, whatever they cover. */
export function labelPlan(
	items: readonly LabelItem[],
	zoom: number,
	always: ReadonlySet<string> = new Set()
): LabelBox[] {
	const tier = (p: number) => (p <= 1 ? 0 : p === 2 ? LABEL_LOD.mid : LABEL_LOD.near);
	const cands = items
		.filter((it) => always.has(it.id) || zoom >= tier(it.priority))
		.map((it) => labelBox(it, zoom))
		.sort(
			(a, b) =>
				Number(always.has(b.id)) - Number(always.has(a.id)) ||
				a.priority - b.priority ||
				(a.id < b.id ? -1 : 1)
		);
	// Gems as obstacles, sorted by their left edge; a label scans only the gems its span reaches.
	const gems = items
		.filter((it) => it.size > 0)
		.map((it) => ({
			id: it.id,
			x: (it.cx - it.size / 2) * zoom,
			y: (it.cy - it.size / 2) * zoom,
			w: it.size * zoom,
			h: it.size * zoom
		}))
		.sort((a, b) => a.x - b.x);
	const maxGem = gems.reduce((n, g) => Math.max(n, g.w), 0);
	const coversGem = (b: LabelBox) => {
		let lo = 0;
		let hi = gems.length;
		const from = b.x - maxGem;
		while (lo < hi) {
			const mid = (lo + hi) >> 1;
			if (gems[mid].x < from) lo = mid + 1;
			else hi = mid;
		}
		for (let i = lo; i < gems.length && gems[i].x < b.x + b.w; i++)
			if (gems[i].id !== b.id && gems[i].w >= b.size * zoom && hits(b, gems[i])) return true;
		return false;
	};
	// ponytail: O(kept × candidates) label check; a grid if a board ever keeps thousands of labels.
	const kept: LabelBox[] = [];
	for (const b of cands) {
		if (!always.has(b.id)) {
			if (kept.some((k) => hits(b, k))) continue;
			if (b.priority >= 2 && coversGem(b)) continue;
		}
		kept.push(b);
	}
	return kept;
}
