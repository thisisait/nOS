// A graph the model shows (renderers.rs Graph), laid out by the face's layered layout
// ($lib/anatomy/graphLayered, one copy of the math): deterministic, no two node boxes
// overlap, a cycle still lays out, and a selection lights a node and its neighbours.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Graph from '../Graph.svelte';
import { layoutGraph, lit, NODE_H, NODE_W, type GraphProps } from './layout';

const organs: GraphProps = {
	title: 'Organs',
	nodes: [
		{ id: 'bone', label: 'Bone', note: 'FastAPI bridge', tone: 'ok' },
		{ id: 'wing', label: 'Wing' },
		{ id: 'keap', label: 'KEAP' }
	],
	edges: [
		{ from: 'bone', to: 'wing', label: 'events' },
		{ from: 'wing', to: 'keap', dashed: true }
	]
};

/** 60 nodes, 120 edges, deterministic but tangled: every node links two others ahead and one behind. */
const big: GraphProps = {
	nodes: Array.from({ length: 60 }, (_, i) => ({ id: `n${i}`, label: `node number ${i}` })),
	edges: Array.from({ length: 120 }, (_, i) => ({ from: `n${i % 60}`, to: `n${(i * 7 + 3) % 60}` }))
};

const html = (graph: GraphProps) => render(Graph, { props: { graph } }).body;

describe('the graph layout', () => {
	it('the same graph lands in the same place, and draws the same markup', () => {
		expect(layoutGraph(big)).toEqual(layoutGraph(big));
		expect(html(big)).toBe(html(big));
	});

	it('no two node boxes overlap at 60 nodes', () => {
		const g = layoutGraph(big);
		expect(g.nodes).toHaveLength(60);
		for (const [i, a] of g.nodes.entries())
			for (const b of g.nodes.slice(i + 1)) {
				const apart =
					a.x + NODE_W <= b.x || b.x + NODE_W <= a.x || a.y + NODE_H <= b.y || b.y + NODE_H <= a.y;
				expect(apart, `${a.id} and ${b.id} overlap`).toBe(true);
			}
		for (const n of g.nodes) {
			expect(n.x).toBeGreaterThanOrEqual(0);
			expect(n.x + NODE_W).toBeLessThanOrEqual(g.W);
			expect(n.y + NODE_H).toBeLessThanOrEqual(g.H);
		}
	});

	it('a cycle still lays out, every edge a path between finite points', () => {
		const cycle: GraphProps = {
			nodes: ['a', 'b', 'c'].map((id) => ({ id, label: id.toUpperCase() })),
			edges: [
				{ from: 'a', to: 'b' },
				{ from: 'b', to: 'c' },
				{ from: 'c', to: 'a' },
				{ from: 'a', to: 'a' }
			]
		};
		const g = layoutGraph(cycle);
		expect(g.nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'c']);
		expect(g.edges).toHaveLength(4);
		for (const e of g.edges) expect(e.d).toMatch(/^M[\d. ,C-]+$/);
		expect(html(cycle).match(/<path[^>]*class="edge/g)?.length).toBe(4);
	});

	it('a node follows its edges: sources to the left of their targets', () => {
		const g = layoutGraph(organs);
		const x = (id: string) => g.nodes.find((n) => n.id === id)!.x;
		expect(x('bone')).toBeLessThan(x('wing'));
		expect(x('wing')).toBeLessThan(x('keap'));
	});

	it('a long label is clipped in its box and said whole in its <title>', () => {
		const long = 'a label much longer than any node box could ever hold';
		const g = layoutGraph({ nodes: [{ id: 'x', label: long }], edges: [] });
		expect(g.nodes[0].text.length * 8 * 0.6).toBeLessThanOrEqual(NODE_W - 8);
		expect(g.nodes[0].text.endsWith('…')).toBe(true);
		expect(html({ nodes: [{ id: 'x', label: long }], edges: [] })).toContain(`<title>${long}`);
	});
});

describe('selecting a node lights it and its neighbours', () => {
	it('nothing selected lights nothing; a node lights itself and every node one edge away', () => {
		expect(lit([], organs.edges).size).toBe(0);
		expect([...lit(['wing'], organs.edges)].sort()).toEqual(['bone', 'keap', 'wing']);
		expect([...lit(['bone'], organs.edges)].sort()).toEqual(['bone', 'wing']);
	});
});

describe('the graph as markup', () => {
	it('is a labelled group of focusable nodes, not an image', () => {
		const h = html(organs);
		const svg = h.match(/<svg[^>]*>/)?.[0] ?? '';
		expect(svg).toContain('role="group"');
		expect(svg).toMatch(/aria-label="[^"]*Organs[^"]*"/);
		expect(h).not.toContain('role="img"');
		const nodes = h.match(/<g[^>]*class="node[^>]*>/g) ?? [];
		expect(nodes).toHaveLength(3);
		for (const n of nodes) expect(n).toContain('tabindex="0"');
		expect(h).toContain('aria-live="polite"');
	});

	it('a dashed edge is drawn dashed, and a tone is said in words', () => {
		const h = html(organs);
		expect(h.match(/<path[^>]*class="edge[^"]*dashed/g)?.length).toBe(1);
		expect(h).toContain('Bone · bone — FastAPI bridge [ok]');
	});

	it('draws no link, no foreign markup, no script', () => {
		const h = html({
			nodes: [{ id: 'x', label: '<script>x</script>', note: '<img onerror=1>' }],
			edges: []
		});
		expect(h).not.toMatch(/<(a|foreignObject|script|img|image)[\s>]/);
		expect(h).toContain('&lt;img');
	});
});
