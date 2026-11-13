/** Guides: petal-shaped wedges that end at each sector's reach, and where each region's name
 *  stands (outside every visible row near its bearing, off the milestone orbit). Plus the
 *  sector balance the layout uses (rows^0.5 with a floor, hysteresis between refreshes). */
import { angDiff, bearing, clamp, DEG, polar, radius } from './geom';
import type { Point, Sector, TreeNode } from './types';

export interface GuideOptions {
	/** Wedge outer radius = sector reach + wedgePad ("petals"). */
	wedgePad: number;
	/** Rim name distance beyond the reach around its bearing. */
	rimPad: number;
	/** Rows within ±rimWindow of the sector's bearing push its name outward. */
	rimWindow: number;
	/** A rim name never sits inside this radius (use rings[2]). */
	rimMin: number;
	/** Keep clear of the milestone orbit by this much; else jump to orbit + rimOrbitJump. */
	rimOrbitClear: number;
	rimOrbitJump: number;
}

export const DEFAULT_GUIDES: GuideOptions = {
	wedgePad: 90,
	rimPad: 130,
	rimWindow: 14 * DEG,
	rimMin: 966,
	rimOrbitClear: 110,
	rimOrbitJump: 80
};

const mid = (s: Sector) => (s.from + s.to) / 2;

type Row = Pick<TreeNode, 'x' | 'y' | 'system' | 'dormant'>;

/** Outermost visible row of each system; at least R1 (the keystone itself). */
export function sectorReach<N extends Row>(
	nodes: readonly N[],
	sectors: readonly Sector[],
	r1: number,
	visible: (n: N) => boolean
): Map<string, number> {
	const reach = new Map(sectors.map((s) => [s.key, r1]));
	for (const n of nodes) {
		if (!n.system || !reach.has(n.system) || !visible(n)) continue;
		reach.set(n.system, Math.max(reach.get(n.system)!, radius(n)));
	}
	return reach;
}

/** An annular wedge from `inner` to `outer`, as an SVG path centred on (0,0). */
export function wedgePath(s: Sector, inner: number, outer: number): string {
	const p = (r: number, a: number) => {
		const q = polar(r, a);
		return `${q.x.toFixed(1)} ${q.y.toFixed(1)}`;
	};
	const big = s.to - s.from > Math.PI ? 1 : 0;
	return `M ${p(inner, s.from)} L ${p(outer, s.from)} A ${outer} ${outer} 0 ${big} 1 ${p(outer, s.to)} L ${p(inner, s.to)} A ${inner} ${inner} 0 ${big} 0 ${p(inner, s.from)} Z`;
}

/** Where a sector's name stands. Names are horizontal, so a narrow sector next to a big one
 *  must clear the big one's rows too: every visible row within ±window of the bearing counts. */
export function rimPoint<N extends Row>(
	s: Sector,
	nodes: readonly N[],
	reach: Map<string, number>,
	orbit: number,
	visible: (n: N) => boolean,
	o: GuideOptions = DEFAULT_GUIDES
): Point {
	const a = mid(s);
	const win = Math.max((s.to - s.from) / 2, o.rimWindow);
	let r = Math.max(reach.get(s.key) ?? 0, o.rimMin);
	for (const n of nodes) {
		if (!visible(n)) continue;
		const rr = radius(n);
		if (orbit && rr >= orbit - 1) continue;
		if (Math.abs(angDiff(a, bearing(n))) <= win) r = Math.max(r, rr);
	}
	r += o.rimPad;
	if (orbit && r > orbit - o.rimOrbitClear) r = orbit + o.rimOrbitJump;
	return polar(r, a);
}

/** Sector balance: weight = rows ^ power, with a floor in degrees; radians per key, summing to
 *  a full turn. Sectors under the floor are pinned there and the rest share what is left. */
export function sectorAngles(
	counts: Record<string, number>,
	power = 0.5,
	floorDeg = 14
): Record<string, number> {
	const keys = Object.keys(counts);
	const w: Record<string, number> = {};
	for (const k of keys) w[k] = Math.max(counts[k], 1) ** power;
	const floor = floorDeg * DEG;
	const fixed = new Set<string>();
	let out: Record<string, number> = {};
	for (let i = 0; i < keys.length; i++) {
		const free = Math.PI * 2 - fixed.size * floor;
		const sum = keys.filter((k) => !fixed.has(k)).reduce((a, k) => a + w[k], 0);
		out = {};
		let grew = false;
		for (const k of keys) {
			const a = fixed.has(k) ? floor : (w[k] / sum) * free;
			if (!fixed.has(k) && a < floor) {
				fixed.add(k);
				grew = true;
			}
			out[k] = a;
		}
		if (!grew) break;
	}
	return out;
}

/** Hysteresis for an evolving roadmap: keep the previous angles unless some sector's target
 *  moved by more than `tolerance` (fraction), so the wedges do not breathe on every refresh. */
export function stableAngles(
	prev: Record<string, number> | null,
	next: Record<string, number>,
	tolerance = 0.15
): Record<string, number> {
	if (!prev) return next;
	const keys = Object.keys(next);
	if (keys.some((k) => !(k in prev)) || Object.keys(prev).some((k) => !(k in next))) return next;
	const drift = Math.max(
		...keys.map((k) => Math.abs(next[k] - prev[k]) / clamp(prev[k], 1e-6, Infinity))
	);
	return drift > tolerance ? next : prev;
}
