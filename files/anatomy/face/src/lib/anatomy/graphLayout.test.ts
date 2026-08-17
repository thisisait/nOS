import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { layout, forceLayout, rankNodes, COL_W, PAD, type Layout } from './graphLayout';
import raw from './anatomy-graph.json';
import pin from './graphLayout.force.pin.json';
import { projectGraph, filterForCanvas, NODE_KINDS, type NodeKind } from './graph';

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

// ── force mode (docs/idea/17-loop-split-refactor-graph.md §3) ───────────────

/** The default view — the picture the operator actually opens: every kind
 *  except service/authentik, connected only. Same construction as
 *  GraphView.svelte's `view` → `placed` pipeline. */
function defaultViewInput() {
	const graph = projectGraph(raw);
	const kinds = new Set<NodeKind>(NODE_KINDS.filter((k) => k !== 'service' && k !== 'authentik'));
	const v = filterForCanvas(graph, kinds, true);
	return {
		nodes: v.nodes,
		edges: [...v.edges, ...v.spokes.map((s) => ({ from: s.node, to: s.resource }))]
	};
}

function hashLayout(l: Layout): string {
	const canon = l.nodes.map((n) => [n.id, n.x, n.y, n.rank]);
	return createHash('sha256')
		.update(JSON.stringify({ nodes: canon, width: l.width, height: l.height }))
		.digest('hex');
}

describe('forceLayout', () => {
	it('honours the Layout contract on the same node set as layout()', () => {
		const input = defaultViewInput();
		const f = forceLayout(input);
		const l = layout(input);
		// Same ids placed by both modes — this is half of the a11y guarantee:
		// the view renders ONE markup path over placed.nodes, so identical id
		// sets mean every keyboard-focusable node exists in either mode.
		expect(new Set(f.nodes.map((n) => n.id))).toEqual(new Set(l.nodes.map((n) => n.id)));
		expect(f.byId.size).toBe(f.nodes.length);
		expect(f.width).toBeGreaterThan(0);
		expect(f.height).toBeGreaterThan(0);
		for (const n of f.nodes) {
			expect(Number.isFinite(n.x) && Number.isFinite(n.y), `non-finite at ${n.id}`).toBe(true);
		}
	});

	it('handles the empty view', () => {
		const f = forceLayout({ nodes: [], edges: [] });
		expect(f.nodes).toEqual([]);
		expect(f.width).toBe(PAD * 2);
	});

	/**
	 * DETERMINISM, PINNED. The layered mode's docblock states the invariant:
	 * the same graph must land in the same place every render, or every
	 * converge "moves" nodes that did not change. d3-force only holds that
	 * invariant by construction once `randomSource()` is seeded — `jiggle()`
	 * draws from the source when two nodes coincide exactly, which no current
	 * input triggers but no contract prevents.
	 *
	 * Measured 2026-08-17 on this artifact: bit-for-bit identical across
	 * fresh node processes AND across Node 22.23.1/24.19.0 (two V8 majors)
	 * on macOS arm64. Linux was NOT locally established; V8 vendors its own
	 * platform-independent transcendental math, so this hash is expected to
	 * hold on CI's ubuntu runner — if CI ever disagrees with a dev box here,
	 * that is a real determinism finding, not test flake: re-measure before
	 * touching the constant.
	 *
	 * The pin re-freezes on ANY change to the artifact, the filter defaults,
	 * or the force tuning. That is intended — re-run this test, read the new
	 * hash from the failure, and re-pin deliberately. The hash itself lives in
	 * graphLayout.force.pin.json: the fixture-secret gate refuses 64-hex
	 * literals inside test files, and reading the needle out of the fixture is
	 * that gate's own prescribed remedy.
	 */
	it('is deterministic — sha256 of the default-view positions is pinned', () => {
		const input = defaultViewInput();
		const h1 = hashLayout(forceLayout(input));
		const h2 = hashLayout(forceLayout(input));
		expect(h1).toBe(h2);
		expect(h1).toBe(pin.defaultViewPositionsSha256);
	});

	it('earns its place — fewer edge crossings than the layered mode on the default view', () => {
		type Pt = [number, number];
		const ccw = (a: Pt, b: Pt, c: Pt) =>
			(b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
		const cross = (p1: Pt, p2: Pt, p3: Pt, p4: Pt) =>
			ccw(p3, p4, p1) * ccw(p3, p4, p2) < 0 && ccw(p1, p2, p3) * ccw(p1, p2, p4) < 0;
		const count = (l: Layout, edges: { from: string; to: string }[], force: boolean) => {
			const segs = edges.flatMap((e) => {
				const a = l.byId.get(e.from);
				const b = l.byId.get(e.to);
				if (!a || !b) return [];
				// The straight-segment proxy for what the canvas draws: layered
				// anchors right-edge→left-edge (the bezier's endpoints), force
				// anchors centre→centre (the actual line).
				return force
					? [{ e, p: [a.x + 75, a.y + 12] as Pt, q: [b.x + 75, b.y + 12] as Pt }]
					: [{ e, p: [a.x + 150, a.y + 12] as Pt, q: [b.x, b.y + 12] as Pt }];
			});
			let n = 0;
			for (let i = 0; i < segs.length; i++)
				for (let j = i + 1; j < segs.length; j++) {
					const s = segs[i];
					const t = segs[j];
					if (
						s.e.from === t.e.from ||
						s.e.from === t.e.to ||
						s.e.to === t.e.from ||
						s.e.to === t.e.to
					)
						continue;
					if (cross(s.p, s.q, t.p, t.q)) n++;
				}
			return n;
		};
		const input = defaultViewInput();
		const layered = count(layout(input), input.edges, false);
		const forced = count(forceLayout(input), input.edges, true);
		// Measured 2026-08-17: 330 layered, 50 forced. Pin the relation, not the
		// exact numbers — the artifact grows; the reason for the mode must not rot.
		expect(forced).toBeLessThan(layered);
	});
});

describe('mode toggle a11y (GraphView source contract)', () => {
	const src = readFileSync(
		fileURLToPath(new URL('../apps/native/anatomy/GraphView.svelte', import.meta.url)),
		'utf-8'
	);

	it('renders nodes through exactly one markup path, in both modes', () => {
		// One focusable-node template, iterating placed.nodes — the mode toggle
		// swaps only which function produced `placed`, never the markup. This is
		// the other half of the a11y guarantee doc 17 rejected four renderer
		// swaps to keep.
		expect(src.match(/role="button"/g)?.length).toBe(1);
		expect(src).toMatch(/\{#each placed\.nodes as p \(p\.id\)\}/);
		expect(src).toMatch(/tabindex="0"/);
		expect(src).toMatch(/layer withheld, upstreams never surveyed/);
		expect(src).toMatch(/\(layoutMode === 'force' \? forceLayout : layout\)/);
	});
});
