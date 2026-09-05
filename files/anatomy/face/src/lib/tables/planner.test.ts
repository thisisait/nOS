import { describe, it, expect } from 'vitest';
import { rowsToGraph, reparentPayload } from './planner';
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
				{ id: 'a', slug: 'a', title: 'A', track: 'platform', parent: '' },
				{ id: 'b', slug: 'b', title: 'B', track: 'platform', parent: 'a' }
			])
		);
		expect(g.nodes.map((n) => n.id).sort()).toEqual(['a', 'b']);
		expect(g.nodes.find((n) => n.id === 'a')!.data.label).toBe('A');
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

	it('columns by track; children indent right of their depth', () => {
		const g = rowsToGraph(
			table([
				{ id: 'a', slug: 'a', title: 'A', track: 'platform', parent: '' },
				{ id: 'b', slug: 'b', title: 'B', track: 'platform', parent: 'a' },
				{ id: 'z', slug: 'z', title: 'Z', track: 'security', parent: '' }
			])
		);
		const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
		// platform sorts before security → smaller x band
		expect(byId.a.position.x).toBeLessThan(byId.z.position.x);
		// child b is depth 1 → indented right of root a within the same column
		expect(byId.b.position.x).toBeGreaterThan(byId.a.position.x);
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
