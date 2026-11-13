import type { Point } from './types';

export const DEG = Math.PI / 180;

/** Signed smallest angle from a to b, in (-π, π]. */
export const angDiff = (a: number, b: number): number =>
	Math.atan2(Math.sin(b - a), Math.cos(b - a));
export const polar = (r: number, a: number): Point => ({ x: r * Math.cos(a), y: r * Math.sin(a) });
export const radius = (p: Point): number => Math.hypot(p.x, p.y);
export const bearing = (p: Point): number => Math.atan2(p.y, p.x);
export const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/** Interpolate along the tree's own geometry: radius and bearing tween separately, so a node
 *  moved to a neighbouring slot slides along its ring instead of cutting a chord. */
export function tweenPolar(a: Point, b: Point, t: number): Point {
	const ra = radius(a);
	const rb = radius(b);
	if (ra < 1 || rb < 1) return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
	const aa = bearing(a);
	return polar(ra + (rb - ra) * t, aa + angDiff(aa, bearing(b)) * t);
}

export interface Rect {
	x: number;
	y: number;
	w: number;
	h: number;
}

export const rectsOverlap = (a: Rect, b: Rect): boolean =>
	a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
