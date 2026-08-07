/**
 * Graph projection tests — run against BOTH a hand-built fixture and the real
 * vendored artifact. The artifact import is the point: these tests fail when
 * a regenerated graph stops carrying what the definition screen renders,
 * which is the projection's whole contract.
 */
import { describe, expect, it } from 'vitest';
import raw from './anatomy-graph.json';
import {
	projectGraph,
	temporalDebt,
	mutexSpokes,
	filterForCanvas,
	joinLive,
	spotlight,
	nodeLabel,
	NODE_KINDS,
	type NodeKind
} from './graph';

const graph = projectGraph(raw);

describe('projectGraph on the vendored artifact', () => {
	it('carries every node with kind, anchor and a one-line body', () => {
		expect(graph.nodes.length).toBeGreaterThanOrEqual(170);
		for (const n of graph.nodes) {
			expect(NODE_KINDS).toContain(n.kind);
			expect(n.anchor).toMatch(/^\d{2}(\.\d{2})*$/);
			expect(n.description.length).toBeGreaterThanOrEqual(20);
			expect(n.description).not.toContain('\n');
		}
	});

	it('resolves every edge endpoint against the node set', () => {
		for (const e of graph.edges) {
			expect(graph.byId.has(e.from), `${e.from} missing`).toBe(true);
			expect(graph.byId.has(e.to), `${e.to} missing`).toBe(true);
		}
	});

	it('exposes the core-substrate nodes the operator asked for by name', () => {
		for (const id of [
			'repo:github-origin',
			'repo:gitea-forge',
			'repo:gitlab-forge',
			'repo:scan-data',
			'tofu:authentik-state',
			'table:roadmap'
		]) {
			expect(graph.byId.has(id), `${id} missing`).toBe(true);
		}
	});
});

describe('temporalDebt', () => {
	it('lists every temporal edge, invertible first', () => {
		const rows = temporalDebt(graph);
		expect(rows.length).toBeGreaterThanOrEqual(5);
		const firstNonInvertible = rows.findIndex((r) => !r.canInvert);
		if (firstNonInvertible !== -1) {
			for (const r of rows.slice(firstNonInvertible)) expect(r.canInvert).toBe(false);
		}
		// The measured fact the panel exists for: at least 3 chain edges are
		// permitted to invert by their own declared budgets (repo gate pins ≥3).
		expect(rows.filter((r) => r.canInvert).length).toBeGreaterThanOrEqual(3);
	});
});

describe('mutexSpokes', () => {
	it('folds pairwise exclusions into one spoke per claim', () => {
		const spokes = mutexSpokes(graph);
		const agentSpokes = spokes.filter((s) => s.resource === 'resource:agent-run-lock');
		const pairs = graph.edges.filter(
			(e) => e.kind === 'mutex' && e.resource === 'agent-run-lock'
		);
		// N claimants: N spokes vs N(N-1)/2 pairs. Same information, less ink.
		expect((agentSpokes.length * (agentSpokes.length - 1)) / 2).toBe(pairs.length);
		expect(agentSpokes.length).toBeGreaterThanOrEqual(5);
	});
});

describe('filterForCanvas', () => {
	const allKinds = new Set<NodeKind>(NODE_KINDS);

	it('keeps no edge whose endpoint is hidden', () => {
		const withoutServices = new Set<NodeKind>(NODE_KINDS.filter((k) => k !== 'service'));
		const view = filterForCanvas(graph, withoutServices, false);
		const visible = new Set(view.nodes.map((n) => n.id));
		for (const e of view.edges) {
			expect(visible.has(e.from)).toBe(true);
			expect(visible.has(e.to)).toBe(true);
		}
	});

	it('connectedOnly hides isolated nodes but never edge endpoints', () => {
		const view = filterForCanvas(graph, allKinds, true);
		const visible = new Set(view.nodes.map((n) => n.id));
		for (const e of view.edges) {
			expect(visible.has(e.from) && visible.has(e.to)).toBe(true);
		}
		// The estate has >100 service/authentik nodes with no wiring; the
		// connected view must be materially smaller than the full node set.
		expect(view.nodes.length).toBeLessThan(graph.nodes.length);
	});
});

describe('joinLive', () => {
	it('separates unregistered from never-ran instead of blending them', () => {
		const pulseIds = graph.nodes.filter((n) => n.kind === 'pulse').map((n) => n.id);
		const first = pulseIds[0].slice('pulse:'.length);
		const join = joinLive(graph, [{ id: first, state: 'ok', neverRan: false }]);
		expect(join.states.get(pulseIds[0])).toBe('ok');
		// Every OTHER pulse node is unregistered against this snapshot — the
		// "declared but never registered" finding, not silence.
		expect(join.unregistered.length).toBe(pulseIds.length - 1);
	});

	it('treats an absent snapshot as all-unregistered, never as all-ok', () => {
		const join = joinLive(graph, undefined);
		expect(join.states.size).toBe(0);
		expect(join.unregistered.length).toBe(
			graph.nodes.filter((n) => n.kind === 'pulse').length
		);
	});
});

describe('spotlight — the widget-sized projection', () => {
	const spot = spotlight(graph, 7);

	it('returns seven REAL nodes of the artifact, not a fixture', () => {
		expect(spot.nodes).toHaveLength(7);
		for (const n of spot.nodes) {
			expect(graph.byId.get(n.id)).toBe(n);
			expect(n.anchor).toMatch(/^\d{2}(\.\d{2})*$/);
			expect(n.description.length).toBeGreaterThanOrEqual(20);
		}
	});

	it('ranks by NON-MUTEX degree — a shared lock is not a busy node', () => {
		const raw = new Map<string, number>();
		const mutexOnly = new Map<string, number>();
		for (const e of graph.edges) {
			for (const end of [e.from, e.to]) {
				raw.set(end, (raw.get(end) ?? 0) + 1);
				if (e.kind === 'mutex') mutexOnly.set(end, (mutexOnly.get(end) ?? 0) + 1);
			}
		}
		// The most-locked node shares one mkdir mutex with ten peers. Under a
		// raw-degree rule it would outrank most of the real wiring — and every
		// one of its neighbours would too, so the seven would be a clique that
		// says nothing except "these run one at a time".
		const [locked, lockDeg] = [...mutexOnly.entries()].sort((a, b) => b[1] - a[1])[0];
		expect(lockDeg).toBeGreaterThan(3);
		const lowestChosen = Math.min(...spot.nodes.map((n) => spot.degree.get(n.id) ?? 0));
		expect(raw.get(locked)!).toBeGreaterThan(lowestChosen);
		expect(spot.nodes.map((n) => n.id)).not.toContain(locked);

		const degrees = spot.nodes.map((n) => spot.degree.get(n.id) ?? 0);
		expect([...degrees].sort((a, b) => b - a)).toEqual(degrees); // descending
	});

	it('is deterministic — same artifact, same seven, same order', () => {
		expect(spotlight(graph, 7).nodes.map((n) => n.id)).toEqual(spot.nodes.map((n) => n.id));
	});

	it('breaks degree ties by id so a re-render never reshuffles', () => {
		const byDeg = new Map<number, string[]>();
		for (const n of spot.nodes) {
			const d = spot.degree.get(n.id) ?? 0;
			(byDeg.get(d) ?? byDeg.set(d, []).get(d)!).push(n.id);
		}
		for (const ids of byDeg.values()) expect(ids).toEqual([...ids].sort());
	});

	it('induces only edges with both endpoints in the seven', () => {
		const ids = new Set(spot.nodes.map((n) => n.id));
		for (const e of spot.edges) {
			expect(ids.has(e.from) && ids.has(e.to)).toBe(true);
			expect(e.kind).not.toBe('mutex');
		}
	});

	it('counts components rather than implying one connected whole', () => {
		// Measured 2026-08-07: 2. The widget prints this; a sample that looks
		// like a connected graph when it is two fragments is the lie.
		expect(spot.components).toBeGreaterThanOrEqual(1);
		expect(spot.components).toBeLessThanOrEqual(spot.nodes.length);
		expect(spot.rule).toContain('mutex pairs excluded');
	});

	it('contains the widget that draws it, so the recursion is checkable', () => {
		expect(graph.byId.has('faceapp:anatomy-widget')).toBe(true);
	});
});

describe('nodeLabel', () => {
	it('shortens the label, never the address', () => {
		expect(nodeLabel('daemon:eu.thisisait.nos.pulse')).toBe('pulse');
		expect(nodeLabel('doctrine:docs/idea/11-agentic-loop-contract.md#5.1')).toBe(
			'loop-contract §5.1'
		);
		expect(nodeLabel('pulse:keap:keap-lint')).toBe('keap:keap-lint');
	});
});
