import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
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

type Snapshot = { positions: (string | number)[][]; width: number; height: number };

function snapshot(l: Layout): Snapshot {
	return {
		positions: l.nodes.map((n) => [n.id, n.x, n.y, n.rank]),
		width: l.width,
		height: l.height
	};
}

/** Every way `got` differs from `want` beyond TOL px per coordinate; rank,
 *  node set and node order are exact. Empty means "the same picture". */
const TOL = 1;
function driftFrom(want: Snapshot, got: Snapshot): string[] {
	const ids = (s: Snapshot) => s.positions.map((r) => r[0] as string);
	const [w, g] = [ids(want), ids(got)];
	if (w.join('\n') !== g.join('\n')) {
		const missing = w.filter((id) => !g.includes(id));
		const added = g.filter((id) => !w.includes(id));
		return [`node set/order differs — missing [${missing}], added [${added}]`];
	}
	const out: string[] = [];
	const far = (a: number, b: number) => Math.abs(a - b) > TOL;
	want.positions.forEach(([id, x, y, rank], i) => {
		const [, gx, gy, gr] = got.positions[i] as [string, number, number, number];
		if (far(x as number, gx) || far(y as number, gy) || rank !== gr)
			out.push(`${id}: pinned (${x},${y}) rank ${rank}, got (${gx},${gy}) rank ${gr}`);
	});
	if (far(want.width, got.width) || far(want.height, got.height))
		out.push(`canvas: pinned ${want.width}×${want.height}, got ${got.width}×${got.height}`);
	return out;
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
	 * Measured 2026-08-17: bit-for-bit identical across fresh node processes
	 * AND across Node 22.23.1/24.19.0 (two V8 majors) on macOS arm64. The
	 * 08-17 hope that the hash would hold on CI's ubuntu runner was WRONG —
	 * CI arbitrated 08-18 and the raw floats are ISA-bound: linux/arm64
	 * matches macOS bit-for-bit, x86_64 does not (a linux/amd64 container
	 * reproduces CI's exact divergent hash; max drift 2.1e-06 px after 400
	 * ticks). forceLayout() now rounds emitted coordinates to whole px, which
	 * absorbs that drift with a measured ~257× margin, so ONE pin holds on
	 * every platform again — see the rounding docblock in graphLayout.ts.
	 * If this test ever splits by platform anyway, re-measure the same way:
	 * `docker run --platform linux/amd64 node:22` over an esbuild bundle of
	 * this file's default-view input, and diff per-node floats first.
	 *
	 * It split again 2026-10-06 at 148 default-view nodes, so the hash was
	 * retired for a positions snapshot compared within TOL px: a 1-px rounding
	 * flip passes, a moved/added/lost node or a rank change does not.
	 *
	 * The pin re-freezes on ANY real change to the artifact, the filter
	 * defaults, or the force tuning. That is intended — re-freeze deliberately:
	 * `FACE_LAYOUT_REPIN=1 npx vitest run src/lib/anatomy/graphLayout.test.ts`
	 * then `npx prettier --write src/lib/anatomy/graphLayout.force.pin.json`.
	 * The snapshot lives in graphLayout.force.pin.json beside graphSha256 (the
	 * fixture-secret gate refuses 64-hex literals inside test files).
	 */
	it('is deterministic — the default-view positions match the pinned snapshot', () => {
		const input = defaultViewInput();
		const s = snapshot(forceLayout(input));
		expect(snapshot(forceLayout(input))).toEqual(s);
		if (process.env.FACE_LAYOUT_REPIN) {
			const pinPath = fileURLToPath(new URL('./graphLayout.force.pin.json', import.meta.url));
			const graph = readFileSync(fileURLToPath(new URL('./anatomy-graph.json', import.meta.url)));
			const graphSha256 = createHash('sha256').update(graph).digest('hex');
			const pinnedAt = new Date().toISOString().slice(0, 10);
			writeFileSync(pinPath, JSON.stringify({ ...pin, pinnedAt, graphSha256, ...s }));
		}
		expect(driftFrom(pin, s)).toEqual([]);
	});

	it('the snapshot tolerance is not blind', () => {
		const s = snapshot(forceLayout(defaultViewInput()));
		const shifted = (i: number, dx: number, rank = 0): Snapshot => ({
			...s,
			positions: s.positions.map((r, j) =>
				j === i ? [r[0], (r[1] as number) + dx, r[2], (r[3] as number) + rank] : r
			)
		});
		expect(driftFrom(s, shifted(0, TOL))).toEqual([]); // the ISA rounding flip
		expect(driftFrom(s, shifted(0, 2))).toHaveLength(1);
		expect(driftFrom(s, shifted(0, 0, 1))).toHaveLength(1);
		expect(driftFrom(s, { ...s, positions: s.positions.slice(1) })[0]).toMatch(/missing/);
		expect(driftFrom(s, { ...s, width: s.width + 2 })).toHaveLength(1);
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
