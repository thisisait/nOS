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
 *  re-render doesn't jump): one column per TRACK, rows stacked within a column
 *  ordered by depth then slug, x indented by depth so hierarchy reads at a
 *  glance. It is a starting placement — the editor slice adds interactive drag
 *  and (later) write-back; read-only view needs only that the graph be legible.
 */
import type { DataTable, DataTableRow } from '$lib/contracts';

export interface PlannerNode {
	id: string;
	position: { x: number; y: number };
	data: {
		label: string;
		slug: string;
		status: string;
		track: string;
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

const COL_W = 320; // horizontal gap between track columns
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

/** Turn a roadmap-shaped DataTable into a graph. Rows with no `id` are skipped
 *  (the BFF guarantees ids; a row without one cannot be an edge endpoint). */
export function rowsToGraph(table: DataTable | null | undefined): PlannerGraph {
	const rows = (table?.rows ?? []).filter((r) => typeof r.id === 'string' && r.id);
	const bySlug = new Map<string, DataTableRow>();
	for (const r of rows) {
		const s = cell(r, 'slug');
		if (s) bySlug.set(s, r);
	}

	// Column per track (stable, sorted); depth per row for the within-column order.
	const tracks = [...new Set(rows.map((r) => cell(r, 'track') || 'untracked'))].sort();
	const trackX = new Map(tracks.map((t, i) => [t, i * COL_W]));
	const depth = new Map(rows.map((r) => [r.id, depthOf(r, bySlug, rows.length)]));

	// Order rows within each track column by (depth, slug) for a stable stack.
	const perTrackCount = new Map<string, number>();
	const nodes: PlannerNode[] = [];
	const dangling = new Set<string>();

	const ordered = [...rows].sort((a, b) => {
		const ta = cell(a, 'track') || 'untracked';
		const tb = cell(b, 'track') || 'untracked';
		if (ta !== tb) return ta < tb ? -1 : 1;
		const da = depth.get(a.id) ?? 0;
		const db = depth.get(b.id) ?? 0;
		if (da !== db) return da - db;
		return cell(a, 'slug') < cell(b, 'slug') ? -1 : 1;
	});

	for (const r of ordered) {
		const track = cell(r, 'track') || 'untracked';
		const d = depth.get(r.id) ?? 0;
		const n = perTrackCount.get(track) ?? 0;
		perTrackCount.set(track, n + 1);
		const parentSlug = cell(r, 'parent');
		const orphan = parentSlug && !bySlug.has(parentSlug) ? parentSlug : undefined;
		if (orphan) dangling.add(orphan);
		nodes.push({
			id: r.id,
			position: { x: (trackX.get(track) ?? 0) + d * INDENT, y: n * ROW_H },
			data: {
				label: cell(r, 'title') || cell(r, 'slug') || r.id,
				slug: cell(r, 'slug'),
				status: cell(r, 'status'),
				track,
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
