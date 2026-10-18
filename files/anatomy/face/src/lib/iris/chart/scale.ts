// Scales for the chart, hand-written (operator ruling 2026-10-13: no runtime libraries).

/** Drops float dust: 0.30000000000000004 -> 0.3. */
const clean = (v: number) => Number(v.toPrecision(12));

/** A step of 1, 2 or 5 times a power of ten giving about `count` steps over `span`. */
export function niceStep(span: number, count: number): number {
	const raw = span / Math.max(count, 1);
	const mag = 10 ** Math.floor(Math.log10(raw));
	const r = raw / mag;
	return clean((r >= Math.sqrt(50) ? 10 : r >= Math.sqrt(10) ? 5 : r >= Math.SQRT2 ? 2 : 1) * mag);
}

/** The multiples of the nice step inside [lo, hi]. */
export function ticks(lo: number, hi: number, count = 5): number[] {
	if (!(hi > lo)) return [lo];
	const step = niceStep(hi - lo, count);
	const out: number[] = [];
	for (let i = Math.ceil(lo / step - 1e-9); i <= Math.floor(hi / step + 1e-9); i++)
		out.push(clean(i * step));
	return out;
}

/** [d0, d1] onto [r0, r1]; a zero-width domain maps to the middle of the range. */
export const linear = (d0: number, d1: number, r0: number, r1: number) => (v: number) =>
	d1 === d0 ? (r0 + r1) / 2 : r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);

/** n equal steps over [r0, r1]: `at` is a step's start, `mid` its centre. */
export function band(n: number, r0: number, r1: number) {
	const step = (r1 - r0) / Math.max(n, 1);
	return { step, at: (i: number) => r0 + step * i, mid: (i: number) => r0 + step * (i + 0.5) };
}

export type Tick = { v: number; label: string };

const HOUR = 3600e3,
	DAY = 24 * HOUR,
	MONTH = 30.44 * DAY;
const iso = (v: number) => new Date(v).toISOString();

/** UTC ticks in [lo, hi] (epoch ms), stepped by hours, days, months or years, each labelled in its unit. */
export function timeTicks(lo: number, hi: number, count = 5): Tick[] {
	if (!(hi > lo)) return [{ v: lo, label: iso(lo).slice(0, 10) }];
	const target = (hi - lo) / Math.max(count, 1);
	const fixed = (step: number, label: (s: string) => string) => {
		const out: Tick[] = [];
		for (let v = Math.ceil(lo / step) * step; v <= hi; v += step)
			out.push({ v, label: label(iso(v)) });
		return out;
	};
	const hours = [1, 2, 3, 6, 12].find((h) => h * HOUR >= target);
	if (hours) return fixed(hours * HOUR, (s) => s.slice(11, 16));
	const days = [1, 2, 7, 14].find((d) => d * DAY >= target);
	if (days) return fixed(days * DAY, (s) => s.slice(5, 10));
	// Months and years are calendar steps, so walk the calendar, not a fixed width.
	const months = [1, 2, 3, 6].find((m) => m * MONTH >= target);
	const every = months ?? 12 * Math.max(1, niceStep((hi - lo) / (12 * MONTH), count));
	const d = new Date(lo);
	let m = d.getUTCFullYear() * 12 + d.getUTCMonth();
	if (Date.UTC(Math.floor(m / 12), m % 12, 1) < lo) m++;
	m = Math.ceil(m / every) * every;
	const out: Tick[] = [];
	for (
		let v = Date.UTC(Math.floor(m / 12), m % 12, 1);
		v <= hi;
		m += every, v = Date.UTC(Math.floor(m / 12), m % 12, 1)
	)
		out.push({ v, label: months ? iso(v).slice(0, 7) : iso(v).slice(0, 4) });
	return out;
}
