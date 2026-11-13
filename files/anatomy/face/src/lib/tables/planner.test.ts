import { describe, it, expect } from 'vitest';
import {
	rowsToGraph,
	reparentPayload,
	frontierStates,
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
	{ id: 'wa', slug: 'w-a', status: 'next', parent: 'w-epic' },
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

	it('rows outside the ring sit in a band below the tree, milestones first', () => {
		const p = at(board());
		const lowest = Math.max(...RING.map((s) => p(s).y), p('f-next').y, p('s-grand').y);
		expect(p('rel-020').y).toBeGreaterThan(lowest);
		expect(p('rel-020').x).toBeLessThan(p('loose').x);
		expect(p('loose').x).toBeLessThan(p('loose-kid').x);
	});

	it('is stable: the same board in another order lays out the same', () => {
		const a = skillTreeLayout(board()).positions;
		const b = skillTreeLayout([...board()].reverse()).positions;
		expect([...b].sort()).toEqual([...a].sort());
	});

	it('names ring systems missing from the board', () => {
		expect(skillTreeLayout(systems().filter((r) => r.slug !== 'keel')).absent).toEqual(['keel']);
	});
});
