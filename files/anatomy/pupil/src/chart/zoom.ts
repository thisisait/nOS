// Zoom and pan as a pure transform: screen = world * k + t, over a plot of w x h.

export type Zoom = { k: number; tx: number; ty: number };
export type Box = { w: number; h: number; xOnly?: boolean };

export const IDENTITY: Zoom = { k: 1, tx: 0, ty: 0 };
const MAX = 20;
const STEP = 1.5;

/** Never out past 1, never in past MAX, never panned off the content; `|| 0` turns -0 into 0. */
function clamp(z: Zoom, box: Box): Zoom {
	const k = Math.min(Math.max(z.k, 1), MAX);
	const c = (t: number, size: number) => Math.min(Math.max(t, size * (1 - k)), 0) || 0;
	return { k, tx: c(z.tx, box.w), ty: box.xOnly ? 0 : c(z.ty, box.h) };
}

/** Scale by `factor` about the screen point `at`, which stays where it is. */
export function zoomAt(z: Zoom, [x, y]: [number, number], factor: number, box: Box): Zoom {
	const k = Math.min(Math.max(z.k * factor, 1), MAX);
	return clamp({ k, tx: x - ((x - z.tx) / z.k) * k, ty: y - ((y - z.ty) / z.k) * k }, box);
}

/** A wheel notch of 300 (deltaY) doubles or halves. */
export const wheel = (z: Zoom, at: [number, number], deltaY: number, box: Box) => zoomAt(z, at, 2 ** (-deltaY / 300), box);

export const drag = (z: Zoom, dx: number, dy: number, box: Box) => clamp({ k: z.k, tx: z.tx + dx, ty: z.ty + dy }, box);

/** + (or =) and - zoom about the centre, 0 resets; any other key is not the zoom's. */
export function key(z: Zoom, k: string, box: Box): Zoom | null {
	const centre: [number, number] = [box.w / 2, box.h / 2];
	if (k === '+' || k === '=') return zoomAt(z, centre, STEP, box);
	if (k === '-') return zoomAt(z, centre, 1 / STEP, box);
	if (k === '0') return IDENTITY;
	return null;
}
