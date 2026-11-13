/** Labels v2: measured (never estimated), wrapped (never clipped), hung outward from the gem,
 *  then thinned by a collision pass. Pure; the only browser piece is the Measurer (measure.ts).
 *  v1 estimated `chars × a constant` and let CSS cut with "…": any font whose advance differed
 *  (SF Mono on a Mac, a missing AIT Mono) cut even short names (operator 11-13). */
import { clamp, rectsOverlap } from './geom';
import type { GemRank } from '../planner';
import type { LabelSeed } from './types';

export type LabelKind = 'rim' | 'big' | 'small';
export const kindOf = (s: Pick<LabelSeed, 'priority'>): LabelKind =>
	s.priority === 0 ? 'rim' : s.priority === 1 ? 'big' : 'small';

/** Box metrics per kind — MUST match .lbl in SkillTreeView.svelte (padding + 1px border). */
export interface KindBox {
	padX: number;
	padY: number;
	lineH: number;
}
export const BOX: Record<LabelKind, KindBox> = {
	small: { padX: 8, padY: 2, lineH: 14 }, // padding 1px 7px + border 1px · line-height 14px → 18 for one line
	big: { padX: 9, padY: 1, lineH: 20 }, // padding 0 8px + border 1px · line-height 20px → 22
	rim: { padX: 9, padY: 1, lineH: 22 } // padding 0 8px + border 1px · line-height 22px → 24
};

export interface Measurer {
	/** Content width in CSS px of `text` as `kind` draws it (case transform and tracking included). */
	width(kind: LabelKind, text: string): number;
}

export interface LabelPolicy {
	lod: { rimUntil: number; system: number; mid: number; near: number };
	gap: number;
	/** Gem minimum on-screen scale per rank — MUST equal the CSS --min. */
	gemMin: Record<GemRank, number>;
	/** Max content width of a small label at zoom z. */
	budget(z: number, pinned: boolean): number;
	/** Max lines of a small label at zoom z (epics, priority 2, get one more below `near`). */
	maxLines(z: number, pinned: boolean, priority: number): number;
}

export const DEFAULT_POLICY: LabelPolicy = {
	lod: { rimUntil: 0.55, system: 0.55, mid: 0.55, near: 1.0 },
	gap: 6,
	gemMin: { core: 0.5, system: 0.42, epic: 0.36, leaf: 0.34, halo: 0.3 },
	budget: (z, pinned) => (pinned ? 300 : clamp(210 + (z - 1) * 100, 190, 300)),
	maxLines: (z, pinned, priority) =>
		pinned ? 12 : z < 1 ? (priority === 2 ? 3 : 2) : z < 1.3 ? 4 : z < 1.9 ? 5 : 7
};

export const rankOf = (seed: Pick<LabelSeed, 'cls'>): GemRank =>
	(/rank-(\w+)/.exec(seed.cls)?.[1] as GemRank) ?? 'leaf';

/** The gem's on-screen size at zoom z (it never drops below size × gemMin). */
export const visualGemSize = (
	size: number,
	rank: GemRank,
	z: number,
	p: LabelPolicy = DEFAULT_POLICY
): number => Math.max(size * z, size * (p.gemMin[rank] ?? 0));

/** "Law: the doctrine…" → "Law". Complete words, never an ellipsis. Null when there is none. */
export function headline(text: string): string | null {
	const m = /^(.{3,40}?)\s*(?::\s|\s[—–-]\s)/.exec(text);
	return m ? m[1] : null;
}

export interface Wrapped {
	text: string;
	lines: string[];
	/** Widest line, content px. */
	width: number;
	truncated: boolean;
}

/** Greedy word wrap with measured word widths. Big and rim labels never wrap and are never cut.
 *  A small label is cut only past maxLines, at a word boundary, with "…" — and fit() prefers a
 *  headline over that. A single word longer than the budget overflows; it is never broken. */
export function wrap(
	text: string,
	kind: LabelKind,
	maxW: number,
	maxLines: number,
	m: Measurer
): Wrapped {
	if (kind !== 'small')
		return { text, lines: [text], width: m.width(kind, text), truncated: false };
	const words = text.split(/\s+/).filter(Boolean);
	const sp = m.width(kind, ' ');
	const lines: string[][] = [];
	const widths: number[] = [];
	let cur: string[] = [];
	let cw = 0;
	for (const word of words) {
		const ww = m.width(kind, word);
		if (cur.length && cw + sp + ww > maxW) {
			lines.push(cur);
			widths.push(cw);
			cur = [word];
			cw = ww;
		} else {
			cw = cur.length ? cw + sp + ww : ww;
			cur.push(word);
		}
	}
	if (cur.length) {
		lines.push(cur);
		widths.push(cw);
	}
	let truncated = false;
	if (lines.length > maxLines) {
		truncated = true;
		lines.length = maxLines;
		widths.length = maxLines;
		const last = lines[maxLines - 1];
		const ell = m.width(kind, '…');
		let w = widths[maxLines - 1];
		while (last.length > 1 && w + ell > maxW) {
			const gone = last.pop()!;
			w -= m.width(kind, gone) + sp;
		}
		last[last.length - 1] += '…';
		widths[maxLines - 1] = w + ell;
	}
	return { text, lines: lines.map((l) => l.join(' ')), width: Math.max(0, ...widths), truncated };
}

/** Which string a label shows: the full title, or a complete headline when the title would be cut. */
export function fit(
	seed: LabelSeed,
	z: number,
	pinned: boolean,
	m: Measurer,
	p: LabelPolicy = DEFAULT_POLICY
): Wrapped {
	const kind = kindOf(seed);
	const maxW = p.budget(z, pinned);
	const maxL = p.maxLines(z, pinned, seed.priority);
	if (!pinned && seed.short && z < p.lod.near) return wrap(seed.short, kind, maxW, maxL, m);
	const full = wrap(seed.text, kind, maxW, maxL, m);
	if (!full.truncated || pinned) return full;
	const head = seed.short ?? headline(seed.text);
	if (head) {
		const h = wrap(head, kind, maxW, maxL, m);
		if (!h.truncated) return h;
	}
	return full;
}

export type Align = 'start' | 'mid' | 'end';

export interface LabelBox {
	seed: LabelSeed;
	kind: LabelKind;
	wrapped: Wrapped;
	/** Zoomed-flow px (add the viewport translation to draw). */
	x: number;
	y: number;
	w: number;
	h: number;
	align: Align;
}

export function boxSize(kind: LabelKind, w: Wrapped): { w: number; h: number } {
	const b = BOX[kind];
	return { w: Math.ceil(w.width) + 2 * b.padX + 1, h: w.lines.length * b.lineH + 2 * b.padY };
}

/** Hang the box outward from its anchor (the gem centre, or a rim point) along the ray from
 *  the core: right half starts at the anchor, left half ends there, top/bottom centre. */
export function place(
	seed: LabelSeed,
	wrapped: Wrapped,
	z: number,
	p: LabelPolicy = DEFAULT_POLICY
): LabelBox {
	const kind = kindOf(seed);
	const { w, h } = boxSize(kind, wrapped);
	const r = Math.hypot(seed.cx, seed.cy);
	const ux = r ? seed.cx / r : 0;
	const uy = r ? seed.cy / r : 1;
	const off = seed.size ? visualGemSize(seed.size, rankOf(seed), z, p) / 2 + p.gap : 0;
	const ax = seed.cx * z + ux * off;
	const ay = seed.cy * z + uy * off;
	const align: Align = ux > 0.35 ? 'start' : ux < -0.35 ? 'end' : 'mid';
	const x = align === 'start' ? ax : align === 'end' ? ax - w : ax - w / 2;
	const y = uy > 0.35 ? ay : uy < -0.35 ? ay - h : ay - h / 2;
	return { seed, kind, wrapped, x, y, w, h, align };
}

export function lodVisible(seed: LabelSeed, z: number, p: LabelPolicy = DEFAULT_POLICY): boolean {
	if (/\brank-core\b/.test(seed.cls)) return true;
	const pr = seed.priority;
	if (pr === 0) return z < p.lod.rimUntil;
	if (pr === 1) return z >= p.lod.system;
	if (pr === 2) return z >= p.lod.mid;
	return z >= p.lod.near;
}

export interface PickContext {
	measurer: Measurer;
	policy?: LabelPolicy;
	/** Hovered / selected: always shown, full text, first in the pass. */
	pinned?: ReadonlySet<string>;
	/** The selected row's ancestry: always shown, second in the pass. */
	trail?: ReadonlySet<string>;
}

/** The collision pass. Order: pinned, trail, then priority (rim, keystones, epics, rows), then
 *  id for determinism. A label is dropped if it overlaps an accepted label, or (rows and epics)
 *  if it covers a gem at least as big as its own. Run it on a quantised zoom step, never per
 *  pan frame; place() alone is cheap enough per frame. */
export function pickLabels(seeds: readonly LabelSeed[], z: number, ctx: PickContext): LabelBox[] {
	const p = ctx.policy ?? DEFAULT_POLICY;
	const pinned = ctx.pinned ?? new Set<string>();
	const trail = ctx.trail ?? new Set<string>();
	const rankScore = (s: LabelSeed) => (pinned.has(s.id) ? 0 : trail.has(s.id) ? 1 : 2);
	const cand = seeds
		.filter((s) => pinned.has(s.id) || trail.has(s.id) || lodVisible(s, z, p))
		.sort(
			(a, b) =>
				rankScore(a) - rankScore(b) ||
				a.priority - b.priority ||
				(a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
		)
		.map((s) => place(s, fit(s, z, pinned.has(s.id), ctx.measurer, p), z, p));

	const gems = seeds
		.filter((s) => s.size > 0)
		.map((s) => {
			const v = visualGemSize(s.size, rankOf(s), z, p);
			return { id: s.id, x: s.cx * z - v / 2, y: s.cy * z - v / 2, w: v, h: v };
		})
		.sort((a, b) => a.x - b.x);
	const maxGem = gems.reduce((m, g) => Math.max(m, g.w), 0);
	const coversGem = (l: LabelBox) => {
		const own = visualGemSize(l.seed.size, rankOf(l.seed), z, p);
		let lo = 0;
		let hi = gems.length;
		const from = l.x - maxGem;
		while (lo < hi) {
			const mid = (lo + hi) >> 1;
			if (gems[mid].x < from) lo = mid + 1;
			else hi = mid;
		}
		for (let i = lo; i < gems.length && gems[i].x < l.x + l.w; i++)
			if (gems[i].id !== l.seed.id && gems[i].w >= own && rectsOverlap(l, gems[i])) return true;
		return false;
	};

	// ponytail: O(kept × candidates) overlap scan; a grid if a board ever keeps thousands of labels.
	const out: LabelBox[] = [];
	// A 2px breathing gap between accepted boxes: the canvas measure is calibrated, not exact,
	// and two labels placed a hair apart otherwise touch on screen (measured on the live board).
	const pad = (r: LabelBox) => ({
		x: r.x - LABEL_GAP,
		y: r.y - LABEL_GAP,
		w: r.w + 2 * LABEL_GAP,
		h: r.h + 2 * LABEL_GAP
	});
	const blocked = (l: LabelBox) =>
		out.some((o) => rectsOverlap(pad(l), o)) || (l.seed.priority >= 2 && coversGem(l));
	for (let l of cand) {
		const forced = pinned.has(l.seed.id) || trail.has(l.seed.id);
		if (!forced && blocked(l)) {
			// A region or keystone name is never dropped for its neighbour: two 14° petals at the
			// top or the bottom put their (horizontal) names side by side, so step the later one
			// outward along its ray until it clears.
			if (l.seed.priority > 1) continue;
			let step = 0;
			for (step = 1; step <= RIM_STEPS && blocked(l); step++)
				l = place(outward(l.seed, step * RIM_STEP), l.wrapped, z, p);
			if (blocked(l)) continue;
		}
		out.push(l);
	}
	return out;
}

const LABEL_GAP = 2;
const RIM_STEP = 60; // flow px per retry outward
const RIM_STEPS = 6;
const outward = (s: LabelSeed, by: number): LabelSeed => {
	const r = Math.hypot(s.cx, s.cy) || 1;
	return { ...s, cx: s.cx + (s.cx / r) * by, cy: s.cy + (s.cy / r) * by };
};
