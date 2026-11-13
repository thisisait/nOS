/** Edge routing: a radial Bézier (d3's linkRadial) so siblings leave the parent along one trunk
 *  and fan out — the tree reads as grown instead of drawn. Straight from the core, into the
 *  halo, and for tiny angles. Paths are centred on the tree origin (the core at 0,0). */
import { angDiff, bearing, polar, radius } from './geom';
import type { GemRank } from '../planner';
import type { Point } from './types';

export type Route = 'curve' | 'orbit' | 'straight';

export interface RouteOptions {
	route: Route;
	/** Where the bend sits between the two radii, 0..1. */
	elbow: number;
}

export const DEFAULT_ROUTE: RouteOptions = { route: 'curve', elbow: 0.5 };

export type End = Point & { rank: GemRank };

const fmt = (p: Point) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`;

export function edgePath(s: End, t: End, opt: RouteOptions = DEFAULT_ROUTE): string {
	const straight = `M ${fmt(s)} L ${fmt(t)}`;
	const rs = radius(s);
	const rt = radius(t);
	if (opt.route === 'straight' || rs < 1 || (t.rank === 'halo' && s.rank !== 'halo'))
		return straight;
	const as = bearing(s);
	const at = bearing(t);
	const da = angDiff(as, at);
	const rm = rs + (rt - rs) * opt.elbow;
	if (Math.abs(da) * rm < 1.5) return straight;
	const a = polar(rm, as);
	const b = polar(rm, at);
	if (opt.route === 'curve') return `M ${fmt(s)} C ${fmt(a)} ${fmt(b)} ${fmt(t)}`;
	const r = rm.toFixed(1);
	return `M ${fmt(s)} L ${fmt(a)} A ${r} ${r} 0 0 ${da > 0 ? 1 : 0} ${fmt(b)} L ${fmt(t)}`;
}

/** Paint order: the lit path is never painted over by an unlit link on a shared trunk. */
export const EDGE_Z: Record<string, number> = { '': 0, front: 1, grown: 2 };
