/** The roadmap evolves: rows appear, ship, and go. Diff two snapshots and say which one-shot
 *  effect each row gets. The view adds the class, then removes it after FX_MS. */
import { radius } from './geom';
import type { TreeNode } from './types';
import type { TreeState } from '../planner';

export interface Diff {
	/** New rows: .fx-sprout */
	sprouted: string[];
	/** Rows gone: keep a ghost for FX_MS.wither with .fx-wither, then drop it. */
	withered: TreeNode[];
	/** Rows that became shipped: .fx-ignite (node + its incoming edge). */
	ignited: string[];
	/** Any other state change (frontier → doing, …): .fx-shift */
	shifted: { id: string; from: TreeState; to: TreeState }[];
	/** Rows whose position moved more than eps: tween with tweenPolar. */
	moved: { id: string; from: { x: number; y: number }; to: { x: number; y: number } }[];
}

export const FX_MS = {
	ignite: 1400,
	sprout: 900,
	wither: 900,
	shift: 900,
	move: 650,
	growStep: 160,
	growDraw: 700
};

type Snap = { nodes: readonly TreeNode[] };

export function diffSnapshots(prev: Snap, next: Snap, eps = 2): Diff {
	const a = new Map(prev.nodes.map((n) => [n.id, n]));
	const b = new Map(next.nodes.map((n) => [n.id, n]));
	const d: Diff = { sprouted: [], withered: [], ignited: [], shifted: [], moved: [] };
	for (const [id, n] of b) {
		const o = a.get(id);
		if (!o) {
			d.sprouted.push(id);
			continue;
		}
		if (o.state !== n.state) {
			if (n.state === 'shipped') d.ignited.push(id);
			else d.shifted.push({ id, from: o.state, to: n.state });
		}
		if (Math.hypot(o.x - n.x, o.y - n.y) > eps)
			d.moved.push({ id, from: { x: o.x, y: o.y }, to: { x: n.x, y: n.y } });
	}
	for (const [id, o] of a) if (!b.has(id)) d.withered.push(o);
	// inner rings first, so a refresh reads as growth from the core outward
	const r = (id: string) => radius(b.get(id) ?? { x: 0, y: 0 });
	d.ignited.sort((x, y) => r(x) - r(y));
	d.sprouted.sort((x, y) => r(x) - r(y));
	return d;
}
