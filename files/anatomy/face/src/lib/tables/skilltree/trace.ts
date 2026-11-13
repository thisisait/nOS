/** Ancestry: the path you would have to allocate. Hover/selection tracing, breadcrumb labels,
 *  keyboard navigation and the grow order all read it. */
import { bearing } from './geom';
import { CORE_ID, type Point, type TreeEdge } from './types';

export const edgeKey = (e: Pick<TreeEdge, 'source' | 'target'>) => `${e.source}>${e.target}`;

export function parentMap(edges: readonly TreeEdge[]): Map<string, string> {
	const m = new Map<string, string>();
	for (const e of edges) if (!m.has(e.target)) m.set(e.target, e.source);
	return m;
}

/** Children sorted clockwise by bearing, so ←/→ walk them in screen order. */
export function childrenMap(
	edges: readonly TreeEdge[],
	pos: (id: string) => Point | undefined
): Map<string, string[]> {
	const m = new Map<string, string[]>();
	for (const e of edges) {
		const list = m.get(e.source) ?? [];
		list.push(e.target);
		m.set(e.source, list);
	}
	for (const list of m.values())
		list.sort((a, b) => bearing(pos(a) ?? { x: 0, y: 0 }) - bearing(pos(b) ?? { x: 0, y: 0 }));
	return m;
}

/** From the parent of `id` up to the root, nearest first. Cycle-safe. */
export function ancestry(id: string, parents: Map<string, string>): string[] {
	const out: string[] = [];
	const seen = new Set([id]);
	let cur = parents.get(id);
	while (cur && !seen.has(cur)) {
		out.push(cur);
		seen.add(cur);
		cur = parents.get(cur);
	}
	return out;
}

export interface Trace {
	nodes: Set<string>;
	edges: Set<string>;
	/** The first ancestor that is not lit (shipped/allocated), if any: the real blocker. */
	blocker: string | null;
}

export function trace(
	id: string,
	parents: Map<string, string>,
	lit: (id: string) => boolean
): Trace {
	const chain = [id, ...ancestry(id, parents)];
	const nodes = new Set(chain);
	const edges = new Set<string>();
	for (let i = 0; i < chain.length - 1; i++) edges.add(`${chain[i + 1]}>${chain[i]}`);
	// nearest-to-core unlit ancestor = the row that has to grow first
	let blocker: string | null = null;
	for (const a of chain.slice(1)) if (a !== CORE_ID && !lit(a)) blocker = a;
	return { nodes, edges, blocker };
}

/** BFS distance from the core: the grow animation's step index. Rows the core does not reach
 *  (the halo, loose milestones) grow afterwards from their own roots, starting at max + 1. */
export function growIndex(
	ids: readonly string[],
	edges: readonly TreeEdge[],
	root = CORE_ID
): Map<string, number> {
	const kids = new Map<string, string[]>();
	const hasParent = new Set<string>();
	for (const e of edges) {
		kids.set(e.source, [...(kids.get(e.source) ?? []), e.target]);
		hasParent.add(e.target);
	}
	const d = new Map<string, number>();
	const bfs = (seeds: string[], start: number) => {
		const q: string[] = [];
		for (const s of seeds)
			if (!d.has(s)) {
				d.set(s, start);
				q.push(s);
			}
		for (let i = 0; i < q.length; i++) {
			const cur = q[i];
			for (const k of kids.get(cur) ?? [])
				if (!d.has(k)) {
					d.set(k, d.get(cur)! + 1);
					q.push(k);
				}
		}
	};
	bfs([root], 0);
	const max = Math.max(0, ...d.values());
	bfs(
		ids.filter((id) => !d.has(id) && !hasParent.has(id)),
		max + 1
	);
	for (const id of ids) if (!d.has(id)) d.set(id, max + 1); // cycles only
	return d;
}
