// A graph (renderers.rs Graph) as geometry: the face's layered layout places each node box
// (one copy of the math, $lib/anatomy/graphLayered), edges are cubic paths between box
// sides, a back edge or a loop bends below. Pure, so vitest runs it in node.
import { layout } from '$lib/anatomy/graphLayered';
import { FONT, GLYPH } from '../chart/geometry';
import type { Component } from '../wire';

export type GraphProps = Extract<Component, { kind: 'graph' }>['props'];
export type GEdge = GraphProps['edges'][number];
export type PlacedNode = { id: string; text: string; tip: string; tone?: string; x: number; y: number };
export type PlacedEdge = { i: number; from: string; to: string; d: string; dashed: boolean; tip: string; label?: { t: string; x: number; y: number } };

export const NODE_W = 150, NODE_H = 24;
const PADX = 4, BEND = 28, EDGE_LABEL = 22;

const clip = (s: string, n: number) => (s.length <= n ? s : s.slice(0, n - 1) + '…');
const r1 = (n: number) => Math.round(n * 10) / 10;

export const nodeTip = (n: GraphProps['nodes'][number]) =>
	`${n.label} · ${n.id}${n.note ? ` — ${n.note}` : ''}${n.tone ? ` [${n.tone}]` : ''}`;

export function layoutGraph(g: GraphProps) {
	const placed = layout({ nodes: g.nodes, edges: g.edges });
	const at = new Map(placed.nodes.map((p) => [p.id, p]));
	const label = new Map(g.nodes.map((n) => [n.id, n.label]));
	const room = Math.floor((NODE_W - 2 * PADX) / GLYPH);
	const nodes: PlacedNode[] = g.nodes.map((n) => {
		const p = at.get(n.id)!;
		return { id: n.id, text: clip(n.label, room), tip: nodeTip(n), tone: n.tone, x: p.x, y: p.y };
	});
	const edges: PlacedEdge[] = g.edges.map((e, i) => {
		const [a, b] = [at.get(e.from)!, at.get(e.to)!];
		let d: string, mid: [number, number];
		if (b.rank > a.rank) {
			const [x1, y1, x2, y2] = [a.x + NODE_W, a.y + NODE_H / 2, b.x, b.y + NODE_H / 2];
			const dx = Math.max((x2 - x1) / 2, 20);
			d = `M${x1} ${y1} C${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
			mid = [(x1 + x2) / 2, (y1 + y2) / 2 - 3];
		} else {
			// Back, sideways or a loop: bottom of one box to the bottom of the other, bent below both.
			const [x1, y1, x2, y2] = [a.x + NODE_W / 2 + (a === b ? 20 : 0), a.y + NODE_H, b.x + NODE_W / 2 - (a === b ? 20 : 0), b.y + NODE_H];
			const low = Math.max(y1, y2) + BEND;
			d = `M${x1} ${y1} C${x1} ${low}, ${x2} ${low}, ${x2} ${y2}`;
			mid = [(x1 + x2) / 2, low - 3];
		}
		const tip = `${label.get(e.from)} → ${label.get(e.to)}${e.label ? ` · ${e.label}` : ''}${e.dashed ? ' (dashed)' : ''}`;
		const edge: PlacedEdge = { i, from: e.from, to: e.to, d, dashed: !!e.dashed, tip };
		if (e.label) edge.label = { t: clip(e.label, EDGE_LABEL), x: r1(mid[0]), y: r1(mid[1]) };
		return edge;
	});
	// Room below the lowest box for a bent edge and its label.
	const H = Math.max(placed.height, ...nodes.map((n) => n.y + NODE_H + BEND + FONT));
	return { W: placed.width, H, FONT, nodes, edges };
}

/** The selected nodes and every node one edge away; nothing selected lights nothing. */
export function lit(sel: readonly string[], edges: readonly GEdge[]): Set<string> {
	const on = new Set(sel);
	for (const e of edges) {
		if (sel.includes(e.from)) on.add(e.to);
		if (sel.includes(e.to)) on.add(e.from);
	}
	return on;
}
