// SVG path data for the chart's marks, hand-written (no runtime libraries).

export type Pt = [number, number];

const r1 = (n: number) => Math.round(n * 10) / 10;

export const linePath = (pts: Pt[]) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join('');

/** Along `top`, back along `base`, closed: the band between two lines. */
export const areaPath = (top: Pt[], base: Pt[]) =>
	top.length ? `${linePath(top)}L${linePath([...base].reverse()).slice(1)}Z` : '';

/** values[series][x] -> [y0, y1] per series and x: positives pile up from 0, negatives down. */
export function stack(values: number[][]): [number, number][][] {
	const up: number[] = [],
		down: number[] = [];
	return values.map((row) =>
		row.map((v, i) => {
			const base = v < 0 ? (down[i] ?? 0) : (up[i] ?? 0);
			(v < 0 ? down : up)[i] = base + v;
			return v < 0 ? [base + v, base] : [base, base + v];
		})
	);
}

/** [start, end] angles in radians, clockwise from 12 o'clock; all zero is all empty. */
export function pieAngles(values: number[]): [number, number][] {
	const total = values.reduce((a, b) => a + b, 0);
	let a = 0;
	return values.map((v) => {
		const start = a;
		a += total > 0 ? (v / total) * 2 * Math.PI : 0;
		return [start, a];
	});
}

/** A wedge from (cx, cy); a whole turn is drawn as two half arcs (one arc cannot close on itself). */
export function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
	const p = (a: number) => `${r1(cx + r * Math.sin(a))},${r1(cy - r * Math.cos(a))}`;
	if (a1 - a0 >= 2 * Math.PI - 1e-9)
		return `M${p(a0)}A${r},${r} 0 1 1 ${p(a0 + Math.PI)}A${r},${r} 0 1 1 ${p(a0)}Z`;
	return `M${cx},${cy}L${p(a0)}A${r},${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${p(a1)}Z`;
}
