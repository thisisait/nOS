/**
 * Layered DAG layout, hand-rolled — the survey decision
 * (docs/archive/nos-anatomy-graph.md §4.0), re-verified at the time:
 * the face's runtime deps were `html-to-image` only, and vendoring elkjs or
 * dagre for ~40 visible nodes buys iterative crossing minimisation nobody
 * asked for at the cost of a dependency nobody audits. One barycenter pass is
 * enough at this size and its output is deterministic, which matters more
 * here than optimality: the same graph must land in the same place every
 * render, or every converge "moves" nodes that did not change.
 *
 * Algorithm:
 *   1. rank = longest path over the directed edges (data|trigger|temporal —
 *      mutex spokes are undirected and do not rank). Cycles cannot occur
 *      per-kind (the compiler refuses them); the one union-kind feedback loop
 *      is broken for LAYOUT ONLY by ignoring back-edges to already-ranked
 *      nodes — the drawn edge still renders, curving back.
 *   2. order within rank by one barycenter pass over ranked neighbours.
 *   3. coordinates: rank → column, order → row.
 *
 * Pure — no DOM, no Svelte — so vitest runs it in node.
 *
 * 2026-08-17 (docs/idea/17-loop-split-refactor-graph.md §3, operator-
 * assented): `forceLayout()` joins `layout()` as a SECOND mode returning the
 * same `Layout` shape, so the view swaps modes without knowing which
 * produced it. The layered mode stays — it
 * is the right picture for the 8-rank temporal/trigger spine; force is the
 * right one for the default view's crossing count (measured, not inherited:
 * see graphLayout.test.ts). This ends the face's one-runtime-dependency
 * posture: d3-force + its three ISC micro-deps (d3-dispatch, d3-quadtree,
 * d3-timer) are now the audit surface the 2026-04 survey refused to buy.
 */

import {
	forceSimulation,
	forceLink,
	forceManyBody,
	forceCollide,
	forceX,
	forceY,
	type SimulationNodeDatum,
	type SimulationLinkDatum
} from 'd3-force';

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

// ── force mode ──────────────────────────────────────────────────────────────

/** Node box the view draws: 150×24 rect, anchored at the placed top-left. */
const NODE_W = 150;
const NODE_H = 24;

/** Ticks per run. The simulation runs ONCE per filter change (the view's
 *  `$derived` recomputes only when its inputs change), never per frame —
 *  400 ticks on the all-kinds view is ~100 ms, fine as a one-off, absurd
 *  at 60 fps. */
const TICKS = 400;

/**
 * Seeded PRNG (mulberry32) handed to `simulation.randomSource()`.
 *
 * WHY THE HOOK IS HERE: d3-force's `jiggle()` draws from the simulation's
 * random source whenever two nodes coincide EXACTLY (forceLink and
 * forceCollide both call it), so determinism is a property of the input, not
 * a guarantee of the library. Measured 2026-08-17: with d3's phyllotaxis
 * initial placement no coincident pair occurs on the current artifact and
 * even the Math.random-sourced sim reproduced bit-for-bit across fresh node
 * processes — but that is luck of this input. A future graph revision could
 * coincide a pair, draw from Math.random, and every converge would "move"
 * nodes that did not change — the exact failure the layered mode's docblock
 * exists to prevent. The constant seed makes determinism constructional.
 * Pinned by the sha256 test beside this file.
 */
function mulberry32(seed: number): () => number {
	let a = seed >>> 0;
	return () => {
		a = (a + 0x6d2b79f5) | 0;
		let t = Math.imul(a ^ (a >>> 15), 1 | a);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}
const SEED = 0x9e3779b9; // arbitrary constant; changing it re-shuffles every saved mental map

interface SimNode extends SimulationNodeDatum {
	id: string;
}

/**
 * Force-directed layout — the second mode. Same `Layout` contract as
 * `layout()`: top-left-anchored positions, canvas padded to content.
 * `rank` is still the longest-path rank (the inspector and any rank-aware
 * caller keep working in either mode); it just no longer dictates x.
 */
export function forceLayout(input: LayoutInput): Layout {
	if (input.nodes.length === 0) {
		return { nodes: [], byId: new Map(), width: PAD * 2, height: PAD * 2 };
	}
	const rank = rankNodes(input);
	const ids = new Set(input.nodes.map((n) => n.id));
	const simNodes: SimNode[] = input.nodes.map((n) => ({ id: n.id }));
	const links: SimulationLinkDatum<SimNode>[] = input.edges
		.filter((e) => ids.has(e.from) && ids.has(e.to))
		.map((e) => ({ source: e.from, target: e.to }));

	const sim = forceSimulation(simNodes)
		.randomSource(mulberry32(SEED))
		.force(
			'link',
			forceLink<SimNode, SimulationLinkDatum<SimNode>>(links)
				.id((d) => d.id)
				.distance(140)
				.strength(0.4)
		)
		.force('charge', forceManyBody().strength(-460))
		// Circular collision over a 150×24 rect: 58 px keeps rows readable
		// without inflating the canvas to the full 76 px half-diagonal.
		.force('collide', forceCollide(58))
		.force('x', forceX(0).strength(0.045))
		.force('y', forceY(0).strength(0.045))
		.stop();
	sim.tick(TICKS);

	// Positions are simulation CENTRES; the contract wants the rect's top-left,
	// shifted so the content sits at PAD like the layered mode.
	let minX = Infinity;
	let minY = Infinity;
	let maxX = -Infinity;
	let maxY = -Infinity;
	for (const s of simNodes) {
		minX = Math.min(minX, s.x!);
		minY = Math.min(minY, s.y!);
		maxX = Math.max(maxX, s.x!);
		maxY = Math.max(maxY, s.y!);
	}
	const nodes: PlacedNode[] = simNodes.map((s) => ({
		id: s.id,
		rank: rank.get(s.id) ?? 0,
		x: PAD + (s.x! - minX),
		y: PAD + (s.y! - minY)
	}));
	return {
		nodes,
		byId: new Map(nodes.map((n) => [n.id, n])),
		width: PAD * 2 + (maxX - minX) + NODE_W,
		height: PAD * 2 + (maxY - minY) + NODE_H
	};
}
