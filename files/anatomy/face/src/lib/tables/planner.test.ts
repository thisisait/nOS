import { describe, it, expect } from 'vitest';
import {
	rowsToGraph,
	reparentPayload,
	frontierStates,
	specReady,
	skillTreeLayout,
	ORGAN_RING,
	OUTSIDE_RING
} from './planner';
import type { DataTable } from '$lib/contracts';

function table(rows: Record<string, unknown>[]): DataTable {
	return {
		slug: 'roadmap',
		title: 'nOS Roadmap',
		columns: [],
		rows: rows as DataTable['rows'],
		source: 'keap'
	};
}

describe('rowsToGraph', () => {
	it('emits a node per row with a stable id', () => {
		const g = rowsToGraph(
			table([
				{ id: 'a', slug: 'a', title: 'A', kind: 'epic', track: 'platform', parent: '' },
				{ id: 'b', slug: 'b', title: 'B', kind: 'task', track: 'platform', parent: 'a' }
			])
		);
		expect(g.nodes.map((n) => n.id).sort()).toEqual(['a', 'b']);
		expect(g.nodes.find((n) => n.id === 'a')!.data.label).toBe('A');
		expect(g.nodes.find((n) => n.id === 'a')!.data.kind).toBe('epic');
	});

	it('draws a parent->child edge keyed on ids, from the parent SLUG', () => {
		const g = rowsToGraph(
			table([
				{ id: 'p1', slug: 'sec', title: 'Sec', track: 'security', parent: '' },
				{ id: 'c1', slug: 'sec-p1', title: 'P1', track: 'security', parent: 'sec' }
			])
		);
		expect(g.edges).toEqual([{ id: 'p1->c1', source: 'p1', target: 'c1' }]);
	});

	it('roots (empty/absent parent) get no incoming edge', () => {
		const g = rowsToGraph(table([{ id: 'a', slug: 'a', title: 'A', track: 't' }]));
		expect(g.edges).toEqual([]);
	});

	it('a parent slug no row provides is recorded, never an edge to nothing', () => {
		const g = rowsToGraph(table([{ id: 'x', slug: 'x', title: 'X', track: 't', parent: 'ghost' }]));
		expect(g.edges).toEqual([]);
		expect(g.danglingParents).toEqual(['ghost']);
		expect(g.nodes[0].data.orphanParent).toBe('ghost');
	});

	it('columns by organ system in ring order, outside the ring last; children indent', () => {
		const g = rowsToGraph(
			table([
				{ id: 'v', slug: 'voice', title: 'Voice', track: 'x', parent: '' },
				{ id: 'w', slug: 'watch', title: 'Watch', track: 'x', parent: '' },
				{ id: 'a', slug: 'a', title: 'A', track: 'face', parent: 'watch' },
				{ id: 'b', slug: 'b', title: 'B', track: 'platform', parent: 'a' },
				{ id: 'z', slug: 'z', title: 'Z', track: 'face', parent: '' }
			])
		);
		const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
		// a and b share The Watch's column though their tracks differ
		expect([byId.a.data.group, byId.b.data.group]).toEqual(['watch', 'watch']);
		expect(byId.z.data.group).toBe(OUTSIDE_RING);
		// watch before voice (ring order, not alphabetical), outside the ring last
		expect(byId.w.position.x).toBeLessThan(byId.v.position.x);
		expect(byId.v.position.x).toBeLessThan(byId.z.position.x);
		// child b is deeper → indented right of a within the same column
		expect(byId.b.position.x).toBeGreaterThan(byId.a.position.x);
	});

	it('a filtered table keeps its organ system when given the full board states', () => {
		const full = table([
			{ id: 'w', slug: 'watch', status: 'shipped', parent: '' },
			{ id: 'a', slug: 'a', status: 'next', parent: 'watch' }
		]);
		const shown = { ...full, rows: full.rows.filter((r) => r.id === 'a') };
		expect(rowsToGraph(shown).nodes[0].data.group).toBe(OUTSIDE_RING);
		expect(rowsToGraph(shown, frontierStates(full.rows)).nodes[0].data.group).toBe('watch');
	});

	it('is cycle-safe (a<->b parent loop does not hang)', () => {
		const g = rowsToGraph(
			table([
				{ id: 'a', slug: 'a', title: 'A', track: 't', parent: 'b' },
				{ id: 'b', slug: 'b', title: 'B', track: 't', parent: 'a' }
			])
		);
		expect(g.nodes).toHaveLength(2);
		expect(g.edges).toHaveLength(2);
	});

	it('empty / null table yields an empty graph', () => {
		expect(rowsToGraph(null)).toEqual({ nodes: [], edges: [], danglingParents: [] });
		expect(rowsToGraph(table([]))).toEqual({ nodes: [], edges: [], danglingParents: [] });
	});

	it('skips a row without an id (cannot be an edge endpoint)', () => {
		const g = rowsToGraph(table([{ slug: 'a', title: 'A', track: 't' } as never]));
		expect(g.nodes).toEqual([]);
	});
});

describe('reparentPayload', () => {
	const t = () =>
		table([
			{ id: 'root', slug: 'root', title: 'Root', track: 't', parent: '' },
			{ id: 'a', slug: 'a', title: 'A', track: 't', parent: 'root' },
			{ id: 'b', slug: 'b', title: 'B', track: 't', parent: 'a' },
			{ id: 'x', slug: 'x', title: 'X', track: 't', parent: '' }
		]);

	it('builds a minimal {slug,parent} keyed on the CHILD slug', () => {
		expect(reparentPayload(t(), 'x', 'root')).toEqual({ slug: 'x', parent: 'root' });
	});

	it('un-parents on null/empty parent (row becomes a root)', () => {
		expect(reparentPayload(t(), 'a', null)).toEqual({ slug: 'a', parent: '' });
		expect(reparentPayload(t(), 'a', '')).toEqual({ slug: 'a', parent: '' });
	});

	it('refuses a self-parent', () => {
		expect(() => reparentPayload(t(), 'a', 'a')).toThrow(/own parent/);
	});

	it('refuses a cycle — parenting root under its own descendant b', () => {
		// root → a → b; making b the parent of root closes the loop
		expect(() => reparentPayload(t(), 'root', 'b')).toThrow(/cycle/);
	});

	it('refuses unknown child or parent', () => {
		expect(() => reparentPayload(t(), 'ghost', 'root')).toThrow(/unknown row/);
		expect(() => reparentPayload(t(), 'a', 'ghost')).toThrow(/unknown parent/);
	});
});

const RING = [
	'gatehouse',
	'spine',
	'stores',
	'vault',
	'keel',
	'archive',
	'forge',
	'backoffice',
	'commons',
	'watch',
	'wits',
	'clockwork',
	'voice'
];
const systems = () => RING.map((s) => ({ id: s, slug: s, status: 'shipped', parent: '' }));
// A small board: the ring, grown and ungrown parents, a blocked chain, a milestone, an orphan.
const board = () => [
	...systems(),
	{ id: 'we', slug: 'w-epic', status: 'active', parent: 'watch' },
	{
		id: 'wa',
		slug: 'w-a',
		status: 'next',
		parent: 'w-epic',
		body: 'Why.\n\nSLICE 1 SPEC ACCEPTED (top agent 2026-11-13).'
	},
	{ id: 'wd', slug: 'w-doing', status: 'doing', parent: 'watch' },
	{ id: 'wc', slug: 'w-c', status: 'next', parent: 'w-doing' },
	{ id: 'wr', slug: 'w-review', status: 'review', parent: 'watch' },
	{ id: 'wq', slug: 'w-queued', status: 'queued', parent: 'watch' },
	{ id: 'sn', slug: 's-next', status: 'next', parent: 'spine' },
	{ id: 'sc', slug: 's-child', status: 'next', parent: 's-next' },
	{ id: 'sg', slug: 's-grand', status: 'active', parent: 's-child' },
	{ id: 'fs', slug: 'f-shipped', status: 'shipped', parent: 'forge' },
	{ id: 'fn', slug: 'f-next', status: 'next', parent: 'f-shipped' },
	{ id: 'r', slug: 'rel-020', status: 'next', parent: '' },
	{ id: 'l', slug: 'loose', status: 'next', parent: '' },
	{ id: 'lk', slug: 'loose-kid', status: 'next', parent: 'loose' }
];

describe('specReady (mirrors spec_ready in roadmap-status.py)', () => {
	const full = [
		'Goal: the thing.',
		'Slice 1: the first cut.',
		'E2E (operator, Studio): click it.',
		'Must not: widen a token.'
	];

	it('all four parts as labels or headings, any case: ready', () => {
		expect(specReady(full.join('\n'))).toEqual({ ready: true, missing: [] });
		expect(
			specReady('## Goal\nx\n## Smallest slice\nx\n## E2E acceptance (operator)\nx\n## Must not\nx')
				.ready
		).toBe(true);
		expect(
			specReady('GOAL: x. smallest shippable slice x. ACCEPTANCE: x. OUT OF SCOPE: x.').ready
		).toBe(true);
	});

	it('each missing part is named, in order', () => {
		for (let i = 0; i < full.length; i++) {
			const r = specReady(full.filter((_, j) => j !== i).join('\n'));
			expect(r.ready).toBe(false);
			expect(r.missing).toEqual([['goal', 'slice', 'e2e', 'must-not'][i]]);
		}
	});

	it("the top agent's stamp is ready on its own", () => {
		for (const b of [
			'SLICE SPEC ACCEPTED (top agent)',
			'SPEC READY, WAITS',
			'Rulings (explore rounds 1-2)'
		])
			expect(specReady(b).ready).toBe(true);
	});

	it('prose is not a part: a two-line body, tests/e2e/, a bare "never" stay needs-spec', () => {
		expect(specReady('Measured: it breaks.\nInvestigate the fix.')).toEqual({
			ready: false,
			missing: ['goal', 'slice', 'e2e', 'must-not']
		});
		expect(specReady('the goal is to slice tests/e2e/x and never must not').missing).toEqual([
			'goal',
			'slice',
			'e2e',
			'must-not'
		]);
		expect(specReady(null).ready).toBe(false);
	});
});

describe('frontierStates (mirrors roadmap-status.py --frontier ring)', () => {
	it('the generated ring is the apex order: core column, left wing, right wing', () => {
		expect(ORGAN_RING.map((r) => r.key)).toEqual(RING);
		expect(ORGAN_RING.map((r) => r.side).join(',')).toBe(
			'core,core,core,core,core,left,left,left,left,right,right,right,right'
		);
	});

	it('names every row with the state the Python rule gives it', () => {
		const st = frontierStates(board());
		const of = (s: string) => st.get(s)!.state;
		expect(of('watch')).toBe('shipped');
		expect(of('w-epic')).toBe('allocated'); // active under shipped
		expect(of('w-a')).toBe('frontier'); // active opens the frontier
		expect(of('f-next')).toBe('frontier');
		expect(of('s-next')).toBe('frontier');
		expect([of('w-doing'), of('w-review'), of('w-queued')]).toEqual(['doing', 'review', 'dormant']);
		expect(of('rel-020')).toBe('milestone');
		expect([of('loose'), of('loose-kid')]).toEqual(['ungrown', 'ungrown']);
		expect(st.get('w-a')!.system).toBe('watch');
		expect(st.get('loose')!.system).toBe('');
	});

	it('a buildable row carries ready/needs-spec; no other state does', () => {
		const st = frontierStates(board());
		expect(st.get('w-a')).toMatchObject({ state: 'frontier', ready: true, missing: [] });
		expect(st.get('s-next')).toMatchObject({
			state: 'frontier',
			ready: false,
			missing: ['goal', 'slice', 'e2e', 'must-not']
		});
		expect(st.get('w-epic')!.ready).toBe(false); // allocated is buildable too (Python's list)
		for (const s of ['watch', 'w-c', 'w-doing', 'loose', 'rel-020'])
			expect(st.get(s)!.ready).toBeUndefined();
	});

	it('a blocked row names its nearest ungrown ancestor (review/doing do not open it)', () => {
		const st = frontierStates(board());
		expect(st.get('w-c')).toMatchObject({ state: 'blocked', blockedBy: 'w-doing' });
		expect(st.get('s-child')).toMatchObject({ state: 'blocked', blockedBy: 's-next' });
		expect(st.get('s-grand')).toMatchObject({
			state: 'blocked',
			blockedBy: 's-child',
			blockedByStatus: 'next',
			depth: 3
		});
	});
});

describe('skillTreeLayout', () => {
	const at = (rows: ReturnType<typeof board>) => {
		const { positions } = skillTreeLayout(rows);
		const bySlug = new Map(rows.map((r) => [r.slug, r.id]));
		return (s: string) => positions.get(bySlug.get(s)!)!;
	};

	it('core column over the top left-to-right, left wing on the left, right wing on the right', () => {
		const p = at(systems());
		const core = RING.slice(0, 5).map(p);
		expect(core.every((q) => q.y < 0)).toBe(true);
		expect(core.map((q) => q.x)).toEqual([...core.map((q) => q.x)].sort((a, b) => a - b));
		const left = RING.slice(5, 9).map(p); // archive nearest the core, commons lowest
		expect(left.every((q) => q.x < 0)).toBe(true);
		expect(left.map((q) => q.y)).toEqual([...left.map((q) => q.y)].sort((a, b) => a - b));
		const right = RING.slice(9).map(p); // watch nearest the core, voice lowest
		expect(right.every((q) => q.x > 0)).toBe(true);
		expect(right.map((q) => q.y)).toEqual([...right.map((q) => q.y)].sort((a, b) => a - b));
		// the core column's arc is centred on the top: stores sits straight up
		expect(Math.abs(p('stores').x)).toBe(0);
	});

	it('descendants grow outward by depth; a bigger subtree gets a wider sector', () => {
		const p = at(board());
		const r = (s: string) => Math.hypot(p(s).x, p(s).y);
		expect(r('watch')).toBeLessThan(r('w-epic'));
		expect(r('w-epic')).toBeLessThan(r('w-a'));
		expect(r('s-next')).toBeLessThan(r('s-child'));
		expect(r('s-child')).toBeLessThan(r('s-grand'));
		// The Watch (7 rows) pushes its neighbours further round than bare systems do
		const ang = (s: string) => Math.atan2(p(s).y, p(s).x);
		expect(ang('wits') - ang('watch')).toBeGreaterThan(ang('clockwork') - ang('wits'));
	});

	it('milestones orbit beyond the tree at the top; unhung rows form a halo outside, root then child', () => {
		const rows = board();
		const p = at(rows);
		const r = (s: string) => Math.hypot(p(s).x, p(s).y);
		const lay = skillTreeLayout(rows);
		const treeOuter = Math.max(...RING.map(r), r('f-next'), r('s-grand'));
		expect(lay.orbit).toBeGreaterThan(treeOuter);
		expect(r('rel-020')).toBe(lay.orbit);
		expect(p('rel-020').y).toBeLessThan(0); // the orbit's crown sits over the core column
		expect(lay.halo[0]).toBeGreaterThan(lay.orbit);
		expect(r('loose')).toBeGreaterThanOrEqual(lay.halo[0]);
		expect(r('loose-kid')).toBeGreaterThan(r('loose'));
	});

	it('exposes the guides: one contiguous wedge per system round the circle, rings by depth', () => {
		const lay = skillTreeLayout(board());
		expect(lay.sectors.map((s) => s.key)).toEqual([
			...RING.slice(5, 9).reverse(),
			...RING.slice(0, 5),
			...RING.slice(9)
		]);
		for (let i = 1; i < lay.sectors.length; i++)
			expect(lay.sectors[i].from).toBeCloseTo(lay.sectors[i - 1].to, 9);
		expect(lay.sectors.at(-1)!.to - lay.sectors[0].from).toBeCloseTo(2 * Math.PI, 9);
		expect(lay.rings[0]).toBe(0);
		expect(lay.rings.length).toBe(1 + 1 + 3); // core, ring 1, s-next → s-child → s-grand
		expect(lay.rings).toEqual([...lay.rings].sort((a, b) => a - b));
		expect(skillTreeLayout(systems()).orbit).toBe(0);
		expect(skillTreeLayout(systems()).halo).toEqual([]);
	});

	/** A fully hung board the size of the real one: 13 systems, 3..20 epics each, 0..12 leaves,
	 *  some grand-leaves, one 52-fan epic, 6 milestones; deterministic (LCG). */
	function synthetic(): Record<string, unknown>[] {
		let seed = 7;
		const rnd = (n: number) => (seed = (seed * 48271) % 2147483647) % n;
		const rows: Record<string, unknown>[] = systems();
		const statuses = ['shipped', 'active', 'next', 'queued', 'review', 'doing', 'parked'];
		for (const sys of RING) {
			const epics = 3 + rnd(18);
			for (let e = 0; e < epics; e++) {
				const es = `${sys}-e${e}`;
				rows.push({ slug: es, status: statuses[rnd(4)], parent: sys });
				const leaves = sys === 'spine' && e === 0 ? 52 : rnd(13);
				for (let l = 0; l < leaves; l++) {
					const ls = `${es}-l${l}`;
					rows.push({ slug: ls, status: statuses[rnd(7)], parent: es });
					if (rnd(5) === 0)
						for (let g = 0; g < 1 + rnd(4); g++)
							rows.push({ slug: `${ls}-g${g}`, status: statuses[rnd(7)], parent: ls });
				}
			}
		}
		for (let m = 0; m < 6; m++) rows.push({ slug: `rel-02${m}`, status: 'next', parent: '' });
		while (rows.length < 1100)
			rows.push({ slug: `extra-${rows.length}`, status: 'next', parent: 'voice-e1' });
		return rows.map((r, i) => ({ ...r, id: `s${i}` }));
	}

	it('packs an 1100-row board: no two tree nodes closer than 20px, the orbit inside 1300px', () => {
		const rows = synthetic();
		expect(rows.length).toBeGreaterThanOrEqual(1100);
		const lay = skillTreeLayout(rows as never);
		const pts = rows.map((r) => lay.positions.get(r.id as string)!);
		expect(pts.every(Boolean)).toBe(true);
		// Sorted by x, so the O(n²) pair scan stops early: 1100 rows in well under a second.
		const inTree = pts.filter((p) => Math.hypot(p.x, p.y) < lay.orbit).sort((a, b) => a.x - b.x);
		let min = Infinity;
		for (let i = 0; i < inTree.length; i++)
			for (let j = i + 1; j < inTree.length && inTree[j].x - inTree[i].x < 20; j++)
				min = Math.min(min, Math.hypot(inTree[i].x - inTree[j].x, inTree[i].y - inTree[j].y));
		expect(min).toBeGreaterThanOrEqual(20);
		expect(lay.orbit).toBeLessThan(1300);
		expect(lay.halo).toEqual([]); // every row hangs under a system (milestones orbit)
	});

	it('a crowded ring splits into radial sub-rings instead of pushing the whole board out', () => {
		// Every system holds 10 rows (balanced wedges); one Watch row fans 60 leaves. One ring per
		// depth needed r ≈ 1719 for them (the pre-packing layout); sub-rings keep it under 900.
		const rows = [
			...systems(),
			...RING.flatMap((s) =>
				Array.from({ length: 10 }, (_, i) => ({
					id: `${s}${i}`,
					slug: `${s}-r${i}`,
					status: 'next',
					parent: s
				}))
			),
			...Array.from({ length: 60 }, (_, i) => ({
				id: `l${i}`,
				slug: `watch-l${String(i).padStart(2, '0')}`,
				status: 'next',
				parent: 'watch-r0'
			}))
		];
		const lay = skillTreeLayout(rows);
		const leafRadii = new Set(
			rows
				.filter((r) => r.slug.startsWith('watch-l'))
				.map((r) => Math.round(Math.hypot(lay.positions.get(r.id)!.x, lay.positions.get(r.id)!.y)))
		);
		expect(leafRadii.size).toBeGreaterThanOrEqual(3); // several sub-rings in use
		expect(Math.max(...leafRadii)).toBeLessThan(900);
	});

	it('is stable: the same board in another order lays out the same', () => {
		const a = skillTreeLayout(board()).positions;
		const b = skillTreeLayout([...board()].reverse()).positions;
		expect([...b].sort()).toEqual([...a].sort());
	});

	it('a big system gets room: the ring-1 floor leaves it over a quarter of the circle', () => {
		const rows = [
			...systems(),
			...Array.from({ length: 200 }, (_, i) => ({
				id: `w${i}`,
				slug: `w-${i}`,
				status: 'next',
				parent: 'watch'
			}))
		];
		const w = skillTreeLayout(rows).sectors.find((s) => s.key === 'watch')!;
		expect(w.to - w.from).toBeGreaterThan(Math.PI / 2); // 0.99 rad under the old 150px floor
	});

	it("a milestone's children lead the halo, centred under the orbit's crown, in orbit order", () => {
		const rows = [
			...systems(),
			...Array.from({ length: 30 }, (_, i) => ({
				id: `a${i}`,
				slug: `a-loose-${String(i).padStart(2, '0')}`,
				status: 'next',
				parent: ''
			})),
			{ id: 'r0', slug: 'rel-020', status: 'next', parent: '' },
			{ id: 'r1', slug: 'rel-021', status: 'next', parent: '' },
			{ id: 'k0', slug: 'z-kid-0', status: 'next', parent: 'rel-020' },
			{ id: 'k1', slug: 'y-kid-1', status: 'next', parent: 'rel-021' }
		];
		const { positions } = skillTreeLayout(rows);
		const ang = (id: string) => Math.atan2(positions.get(id)!.y, positions.get(id)!.x);
		const top = -Math.PI / 2;
		for (const k of ['k0', 'k1']) expect(Math.abs(ang(k) - top)).toBeLessThan(Math.PI / 4);
		expect(ang('k0')).toBeLessThan(ang('k1')); // rel-020's child before rel-021's, as the orbit runs
		expect(positions.get('k0')!.x).toBeLessThan(0); // the pair straddles the crown
		expect(positions.get('k1')!.x).toBeGreaterThan(0);
	});

	it('names ring systems missing from the board', () => {
		expect(skillTreeLayout(systems().filter((r) => r.slug !== 'keel')).absent).toEqual(['keel']);
	});
});
