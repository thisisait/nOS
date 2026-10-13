/**
 * Layered DAG layout, hand-rolled and dependency-free: moved here from
 * graphLayout.ts (2026-10-13, genui I5d) so the pupil's graph renderer can
 * import it through `$face` without pulling d3-force. graphLayout.ts
 * re-exports everything below; the algorithm and its docblock live there.
 * This file must import nothing (gate: the pupil's runtime-deps allow-list).
 */

export interface LayoutInput {
	nodes: { id: string }[];
	edges: { from: string; to: string }[];
}

export interface PlacedNode {
	id: string;
	x: number;
	y: number;
	rank: number;
}

export interface Layout {
	nodes: PlacedNode[];
	byId: Map<string, PlacedNode>;
	width: number;
	height: number;
}

export const COL_W = 220;
export const ROW_H = 44;
export const PAD = 24;

/** Longest-path rank. Back-edges (targets already on the DFS stack) are
 *  skipped for ranking only — the union-kind feedback loop stays drawable
 *  without making the layout recurse forever. */
export function rankNodes(input: LayoutInput): Map<string, number> {
	const out = new Map<string, string[]>();
	const ids = new Set(input.nodes.map((n) => n.id));
	for (const e of input.edges) {
		if (!ids.has(e.from) || !ids.has(e.to)) continue;
		(out.get(e.from) ?? out.set(e.from, []).get(e.from)!).push(e.to);
	}
	const rank = new Map<string, number>();
	const onStack = new Set<string>();

	const visit = (id: string): number => {
		const known = rank.get(id);
		if (known !== undefined) return known;
		if (onStack.has(id)) return 0; // back-edge: rank as if terminal
		onStack.add(id);
		let depth = 0;
		for (const next of out.get(id) ?? []) {
			if (onStack.has(next)) continue; // the feedback loop, broken here only
			depth = Math.max(depth, visit(next) + 1);
		}
		onStack.delete(id);
		rank.set(id, depth);
		return depth;
	};
	for (const n of input.nodes) visit(n.id);

	// Longest path ranks from the SINKS; flip so sources sit in column 0.
	const max = Math.max(0, ...rank.values());
	for (const [id, r] of rank) rank.set(id, max - r);
	return rank;
}

export function layout(input: LayoutInput): Layout {
	const rank = rankNodes(input);
	const cols = new Map<number, string[]>();
	for (const n of input.nodes) {
		const r = rank.get(n.id) ?? 0;
		(cols.get(r) ?? cols.set(r, []).get(r)!).push(n.id);
	}

	// Initial order: stable alphabetical (determinism before aesthetics).
	for (const ids of cols.values()) ids.sort();

	// One barycenter pass, left to right: order each column by the mean row of
	// its already-placed neighbours. One pass is deliberate — iterating to a
	// fixpoint buys little at this node count and can oscillate.
	const row = new Map<string, number>();
	const neighbours = new Map<string, string[]>();
	for (const e of input.edges) {
		(neighbours.get(e.to) ?? neighbours.set(e.to, []).get(e.to)!).push(e.from);
		(neighbours.get(e.from) ?? neighbours.set(e.from, []).get(e.from)!).push(e.to);
	}
	const sortedRanks = [...cols.keys()].sort((a, b) => a - b);
	for (const r of sortedRanks) {
		const ids = cols.get(r)!;
		if (r !== sortedRanks[0]) {
			const bary = (id: string): number => {
				const placed = (neighbours.get(id) ?? [])
					.map((n) => row.get(n))
					.filter((v): v is number => v !== undefined);
				return placed.length
					? placed.reduce((a, b) => a + b, 0) / placed.length
					: Number.MAX_SAFE_INTEGER; // unconnected: keep at the bottom, stably
			};
			ids.sort((a, b) => bary(a) - bary(b) || a.localeCompare(b));
		}
		ids.forEach((id, i) => row.set(id, i));
	}

	const nodes: PlacedNode[] = input.nodes.map((n) => {
		const r = rank.get(n.id) ?? 0;
		return {
			id: n.id,
			rank: r,
			x: PAD + r * COL_W,
			y: PAD + (row.get(n.id) ?? 0) * ROW_H
		};
	});
	const width = PAD * 2 + (Math.max(0, ...rank.values()) + 1) * COL_W;
	const height = PAD * 2 + (Math.max(0, ...[...cols.values()].map((c) => c.length)) + 0.5) * ROW_H;
	return { nodes, byId: new Map(nodes.map((n) => [n.id, n])), width, height };
}
