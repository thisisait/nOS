import { describe, expect, it } from 'vitest';
import { layout, rankNodes, COL_W, PAD } from './graphLayout';
import raw from './anatomy-graph.json';
import { projectGraph, filterForCanvas, NODE_KINDS } from './graph';

const chain = {
	nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'lone' }],
	edges: [
		{ from: 'a', to: 'b' },
		{ from: 'b', to: 'c' }
	]
};

describe('rankNodes', () => {
	it('ranks a chain by longest path, sources first', () => {
		const r = rankNodes(chain);
		expect(r.get('a')).toBe(0);
		expect(r.get('b')).toBe(1);
		expect(r.get('c')).toBe(2);
	});

	it('does not hang or crash on the feedback loop the estate really has', () => {
		const r = rankNodes({
			nodes: [{ id: 'x' }, { id: 'y' }],
			edges: [
				{ from: 'x', to: 'y' },
				{ from: 'y', to: 'x' } // the corpus-diff halt shape
			]
		});
		expect(r.size).toBe(2);
	});
});

describe('layout', () => {
	it('is deterministic — the same input lands in the same place', () => {
		const a = layout(chain);
		const b = layout(chain);
		expect(a.nodes).toEqual(b.nodes);
	});

	it('places ranks in columns and pads the canvas', () => {
		const l = layout(chain);
		expect(l.byId.get('a')!.x).toBe(PAD);
		expect(l.byId.get('c')!.x).toBe(PAD + 2 * COL_W);
		expect(l.width).toBeGreaterThan(l.byId.get('c')!.x);
	});

	it('lays out the real filtered graph without collisions inside a column', () => {
		const graph = projectGraph(raw);
		const view = filterForCanvas(graph, new Set(NODE_KINDS), true);
		const l = layout({
			nodes: view.nodes,
			edges: [...view.edges, ...view.spokes.map((s) => ({ from: s.node, to: s.resource }))]
		});
		expect(l.nodes.length).toBe(view.nodes.length);
		const seen = new Set<string>();
		for (const n of l.nodes) {
			const key = `${n.x}:${n.y}`;
			expect(seen.has(key), `collision at ${key} (${n.id})`).toBe(false);
			seen.add(key);
		}
	});
});
