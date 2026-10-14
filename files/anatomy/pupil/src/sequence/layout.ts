// A sequence (renderers.rs Sequence) as geometry: one lifeline per participant, one fixed-height
// row per step. Gaps start at what the two header boxes need and widen until every message label
// fits between the lifelines it joins; notes and phases widen the margins. Pure, so vitest runs it.
//
// measure() and the gap widening follow answer-me-with-html (src/svg/text.js, src/components/sequence.js):
// MIT License, Copyright (c) 2026 Answer me with HTML contributors. Permission is hereby granted, free of
// charge, to any person obtaining a copy of this software and associated documentation files (the
// "Software"), to deal in the Software without restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
// persons to whom the Software is furnished to do so, subject to the following conditions: The above
// copyright notice and this permission notice shall be included in all copies or substantial portions of
// the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
// INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
// OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
// CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
import type { Component } from '../wire';

export type SequenceProps = Extract<Component, { kind: 'sequence' }>['props'];
export type Label = { t: string; x: number; y: number; anchor: 'start' | 'middle' };
type Rect = { x: number; y: number; w: number; h: number };
export type PlacedStep = { i: number; top: number; tip: string } & (
	| { kind: 'message'; from: string; to: string; d: string; dashed: boolean; label: Label }
	| { kind: 'note'; rect: Rect; label: Label }
	| { kind: 'phase'; rule: { x1: number; x2: number; y: number }; rect: Rect; label: Label }
);

export const FONT = 12, STEP = 32;
const MARGIN = 12, TOP = 8, ACTOR_H = 28, PAD = 14, LABEL_PAD = 16, SELF = 30;

const CJK = /[⺀-鿿가-힯豈-﫿︰-﹏＀-￯　-〿]/;
const NARROW = new Set([...'iljtfrI.,:;|!\'`()[]{}']);
const WIDE = new Set([...'mwMOQGD&']);
const WIDEST = new Set([...'W@%']);

/** Estimated width of `s` at `size` by glyph class; it errs wide (never under Helvetica's AFM), so a label never overflows its room. */
export function measure(s: string, size = FONT): number {
	let em = 0;
	for (const ch of s) {
		if (CJK.test(ch) || ch.codePointAt(0)! >= 0x2000) em += 1; // CJK, and symbols, arrows, dashes
		else if (ch === ' ') em += 0.3;
		else if (NARROW.has(ch)) em += 0.34;
		else if (WIDEST.has(ch)) em += 1.02;
		else if (WIDE.has(ch)) em += 0.86;
		else if ((ch >= 'A' && ch <= 'Z') || '+<=>~'.includes(ch)) em += 0.73;
		else em += 0.56;
	}
	return Math.round(em * size * 100) / 100;
}

const r1 = (n: number) => Math.round(n * 10) / 10;

export function layoutSequence(q: SequenceProps) {
	const idx = new Map(q.participants.map((p, i) => [p, i]));
	const actorW = q.participants.map((p) => Math.max(measure(p) + 2 * PAD, 72));
	const gaps = actorW.slice(1).map((w, i) => (actorW[i] + w) / 2 + 24);
	let right = 0;
	// Widening only ever grows a gap, so a span that fitted keeps fitting.
	for (const s of q.steps) {
		if (!('from' in s)) continue;
		const w = measure(s.text) + LABEL_PAD;
		const [a, b] = [idx.get(s.from)!, idx.get(s.to)!];
		if (a === b) {
			if (a < gaps.length) gaps[a] = Math.max(gaps[a], SELF + 6 + w);
			else right = Math.max(right, SELF + 6 + w);
		} else {
			const [lo, hi] = [Math.min(a, b), Math.max(a, b)];
			const span = gaps.slice(lo, hi).reduce((x, y) => x + y, 0);
			if (span < w) gaps[hi - 1] += w - span;
		}
	}
	const xs = [0];
	for (const g of gaps) xs.push(xs[xs.length - 1] + g);
	const last = xs.length - 1;
	let minX = -actorW[0] / 2, maxX = xs[last] + Math.max(actorW[last] / 2, right);
	const notes = q.steps.map((s) => {
		if (!('note' in s)) return null;
		const at = s.over.map((p) => xs[idx.get(p)!]);
		const [lo, hi] = [Math.min(...at), Math.max(...at)];
		const w = Math.max(measure(s.note) + LABEL_PAD, hi - lo + 40);
		const cx = (lo + hi) / 2;
		minX = Math.min(minX, cx - w / 2);
		maxX = Math.max(maxX, cx + w / 2);
		return { cx, w };
	});
	const content = maxX - minX + 2 * MARGIN;
	const phaseW = Math.max(0, ...q.steps.map((s) => ('phase' in s ? measure(s.phase) + LABEL_PAD : 0)));
	const W = r1(Math.max(content, phaseW + 2 * MARGIN));
	// Content is centred when a phase is the widest thing.
	const shift = MARGIN - minX + (W - content) / 2;
	const X = (x: number) => r1(x + shift);
	const first = TOP + ACTOR_H + 12;
	const H = first + q.steps.length * STEP + 12;

	const actors = q.participants.map((name, i) => {
		const x = X(xs[i]);
		return { name, x, box: { x: r1(x - actorW[i] / 2), y: TOP, w: actorW[i], h: ACTOR_H },
			label: { t: name, x, y: TOP + ACTOR_H / 2 + FONT / 3, anchor: 'middle' } as Label };
	});
	const lifelines = actors.map((a) => ({ x: a.x, y1: TOP + ACTOR_H, y2: H - 6 }));
	const steps: PlacedStep[] = q.steps.map((s, i) => {
		const top = first + i * STEP;
		const mid = top + STEP / 2 + FONT / 3;
		if ('from' in s) {
			const [x1, x2] = [actors[idx.get(s.from)!].x, actors[idx.get(s.to)!].x];
			const tip = `${s.from} → ${s.to}: ${s.text}${s.dashed ? ' (reply)' : ''}`;
			const base = { i, top, tip, kind: 'message' as const, from: s.from, to: s.to, dashed: !!s.dashed };
			if (x1 === x2)
				return { ...base, d: `M${x1} ${top + 8} H${x1 + SELF} V${top + STEP - 6} H${x1 + 2}`,
					label: { t: s.text, x: r1(x1 + SELF + 6), y: mid, anchor: 'start' } };
			const y = top + STEP - 6;
			return { ...base, d: `M${x1} ${y} L${r1(x2 + (x2 > x1 ? -2 : 2))} ${y}`,
				label: { t: s.text, x: r1((x1 + x2) / 2), y: y - 6, anchor: 'middle' } };
		}
		if ('note' in s) {
			const { cx, w } = notes[i]!;
			return { i, top, kind: 'note', tip: `note over ${s.over.join(', ')}: ${s.note}`,
				rect: { x: X(cx - w / 2), y: top + 4, w: r1(w), h: STEP - 8 }, label: { t: s.note, x: X(cx), y: mid, anchor: 'middle' } };
		}
		const w = measure(s.phase) + LABEL_PAD;
		return { i, top, kind: 'phase', tip: `phase: ${s.phase}`, rule: { x1: MARGIN, x2: r1(W - MARGIN), y: top + STEP / 2 },
			rect: { x: r1(W / 2 - w / 2), y: top + 6, w: r1(w), h: STEP - 12 }, label: { t: s.phase, x: r1(W / 2), y: mid, anchor: 'middle' } };
	});
	return { W, H, FONT, STEP, actors, lifelines, steps };
}
