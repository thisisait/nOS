// A dated timeline (renderers.rs Timeline) as geometry: one row per lane (an item with no lane
// has its own), spans as bars and instants as dots on one time axis that zooms along x. Pure.
import type { Component } from '../wire';
import { FONT, GLYPH } from './geometry';
import { linear, timeTicks } from './scale';
import type { Box, Zoom } from './zoom';

export type Item = Extract<Component, { kind: 'timeline' }>['props']['items'][number];
export type Mark = { id: string; tip: string; hi: boolean; x: number; y: number; w?: number; label?: { t: string; x: number; y: number } };
export type TimeLayout = {
	W: number; H: number; L: number; R: number; T: number; B: number; FONT: number; ROW: number;
	lanes: { t: string; x: number; y: number }[];
	marks: Mark[];
	xLabels: { t: string; x: number }[];
	/** the now rule's x, or null when now is outside the range or the view */
	now: number | null;
	box: Box;
};

const DATE = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:Z|[+-](\d{2}):(\d{2})))?$/;

/** renderers.rs is_date: YYYY-MM-DD[THH:MM:SS(Z|±HH:MM)], a real calendar day. */
export function isDate(s: string): boolean {
	const m = DATE.exec(s);
	if (!m) return false;
	const [y, mo, d, h = 0, mi = 0, sec = 0, oh = 0, om = 0] = m.slice(1).map((v) => (v === undefined ? undefined : Number(v))) as number[];
	const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
	const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1];
	return days !== undefined && d >= 1 && d <= days && h < 24 && mi < 60 && sec < 60 && oh < 24 && om < 60;
}

/** Time-scaled only when every when, and every until given, is a date; otherwise the ordinal drawing. */
export const timed = (items: readonly Item[]) =>
	items.length > 0 && items.every((it) => isDate(it.when) && (it.until === undefined || isDate(it.until)));

export const tipOf = (it: Item) =>
	`${it.title} · ${it.when}${it.until ? ` → ${it.until}` : ''}${it.note ? ` — ${it.note}` : ''}${it.hi ? ' hi' : ''}${it.lane ? ` [${it.lane}]` : ''}`;

const ROW = 16, T = 4, B = 16, GAP = 3, PAD = 6;
const r1 = (n: number) => Math.round(n * 10) / 10;
/** A long lane keeps its head and its tail, so lanes that differ at the end still differ. */
const clipMid = (s: string, n: number) => (s.length <= n ? s : s.slice(0, Math.ceil((n - 1) / 2)) + '…' + s.slice(s.length - Math.floor((n - 1) / 2)));
const clipEnd = (s: string, n: number) => (s.length <= n ? s : s.slice(0, n - 1) + '…');

export function layoutTimeline(items: readonly Item[], W: number, zoom: Zoom, now: number): TimeLayout {
	const keys: string[] = [];
	const row = items.map((it, i) => {
		const k = it.lane ?? `\u0000${i}`;
		if (!keys.includes(k)) keys.push(k);
		return keys.indexOf(k);
	});
	const H = T + keys.length * ROW + B;
	const named = keys.filter((k) => !k.startsWith('\u0000'));
	const gutter = named.length ? Math.min(Math.max(...named.map((l) => l.length * GLYPH)), W * 0.3) : 0;
	const L = r1(gutter + (named.length ? 2 * GAP : GAP)), R = GAP, pw = W - L - R;
	const mid = (r: number) => T + r * ROW + ROW / 2;
	const lanes = keys.flatMap((k, r) =>
		k.startsWith('\u0000') ? [] : [{ t: clipMid(k, Math.max(Math.floor(gutter / GLYPH), 3)), x: L - GAP, y: r1(mid(r) + FONT / 3) }]);

	const t0 = items.map((it) => Date.parse(it.when));
	const t1 = items.map((it, i) => (it.until ? Date.parse(it.until) : t0[i]));
	const [d0, d1] = [Math.min(...t0), Math.max(...t1)];
	const world = linear(d0, d1, PAD, pw - PAD);
	const sx = (v: number) => L + world(v) * zoom.k + zoom.tx;
	const inPlot = (px: number) => px >= L - 0.05 && px <= W - R + 0.05;

	const marks: Mark[] = items.map((it, i) => {
		const x = r1(sx(t0[i]));
		const mark: Mark = { id: String(i), tip: tipOf(it), hi: !!it.hi, x, y: mid(row[i]) };
		if (it.until !== undefined) mark.w = r1(Math.max(sx(t1[i]) - sx(t0[i]), 2));
		return mark;
	});
	// A title follows its mark, clipped to the room before the next mark on its row or the plot's edge.
	for (const m of marks) {
		const lx = r1(m.x + (m.w ?? 3) + 2);
		const next = Math.min(W - R, ...marks.filter((o) => o.y === m.y && o.x > m.x).map((o) => o.x - 2));
		const room = Math.floor((next - lx) / GLYPH);
		if (lx >= L && room >= 3) m.label = { t: clipEnd(items[Number(m.id)].title, room), x: lx, y: r1(m.y + FONT / 3) };
	}

	const inv = linear(PAD, pw - PAD, d0, d1);
	const [v0, v1] = [inv((0 - zoom.tx) / zoom.k), inv((pw - zoom.tx) / zoom.k)];
	const xLabels = timeTicks(v0, v1, Math.max(2, Math.floor(pw / 60)))
		.map((t) => ({ t: t.label, px: sx(t.v) }))
		.filter((t) => inPlot(t.px))
		.map(({ t, px }) => {
			const half = (t.length * GLYPH) / 2;
			return { t, x: r1(Math.min(Math.max(px, half), W - half)) };
		});
	const nowX = now >= d0 && now <= d1 ? r1(sx(now)) : NaN;
	return { W, H, L, R, T, B, FONT, ROW, lanes, marks, xLabels, now: inPlot(nowX) ? nowX : null, box: { w: pw, h: H, xOnly: true } };
}
