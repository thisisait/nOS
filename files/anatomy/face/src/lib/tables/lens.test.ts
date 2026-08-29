import { describe, expect, it } from 'vitest';
import {
	narrowView,
	resolveView,
	matchRow,
	matchPredicate,
	buildViewProposalPrompt,
	VIEW_ACTIONS
} from './view';
import type { ColumnSpec, DataTable, DataTableRow } from '$lib/contracts';

/**
 * The generative seam: `facets` / `highlights` / `offer`.
 *
 * What is worth pinning is NOT that a valid block renders — that is visible in
 * a screenshot. It is what happens to an INVALID one, because this block may be
 * filled by a local model, and a model's output is untrusted input that happens
 * to be well-formed JSON. The rule under test throughout is: DROP WHOLE AND
 * SAY SO. A repaired predicate still filters rows, just not the ones anybody
 * declared, and it does it under the author's label.
 */
const col = (key: string, kind: string, label = key): ColumnSpec =>
	({ key, label, kind }) as ColumnSpec;

const COLS = [
	col('title', 'text', 'Title'),
	col('status', 'select', 'Status'),
	col('verified', 'select', 'Verified'),
	col('track', 'text', 'Track'),
	col('parent', 'text', 'Parent'),
	col('ordinal', 'number', 'Order'),
	col('target', 'date', 'Target')
];

const row = (r: Partial<DataTableRow> & { id: string }): DataTableRow => r as DataTableRow;

const ROWS = [
	row({
		id: 'a',
		title: 'A',
		status: 'shipped',
		verified: 'contradicted',
		track: 'face',
		ordinal: 1
	}),
	row({ id: 'b', title: 'B', status: 'shipped', verified: 'confirmed', track: 'face', ordinal: 2 }),
	row({ id: 'c', title: 'C', status: 'queued', verified: 'unverified', track: 'keap', parent: 'a' })
];

const table = (view?: unknown, rows = ROWS): DataTable =>
	({ slug: 't', title: 'T', columns: COLS, rows, source: 'keap', view }) as DataTable;

// The block an author (or a model) would write for the roadmap.
const GOOD = {
	style: 'timeline',
	dateColumn: 'target',
	facets: ['track', 'status'],
	highlights: [
		{
			label: 'claimed done, probe disagrees',
			when: [
				{ column: 'status', op: 'eq', value: 'shipped' },
				{ column: 'verified', op: 'eq', value: 'contradicted' }
			]
		}
	],
	offer: {
		label: 'Some rows claim done while a probe disagrees.',
		action: 'focus-highlight',
		when: [{ column: 'verified', op: 'eq', value: 'contradicted' }]
	}
};

describe('narrowView — the trust boundary', () => {
	it('a well-formed block survives intact', () => {
		const { view, dropped } = narrowView(GOOD, COLS);
		expect(dropped).toEqual([]);
		expect(view?.facets).toEqual(['track', 'status']);
		expect(view?.highlights?.[0].when).toHaveLength(2);
		expect(view?.offer?.action).toBe('focus-highlight');
	});

	it('a hallucinated column disappears and is REPORTED, not repaired', () => {
		const { view, dropped } = narrowView({ ...GOOD, facets: ['track', 'priority'] }, COLS);
		expect(view?.facets).toEqual(['track']);
		expect(dropped).toContain('facet:priority');
	});

	it('one bad predicate voids the WHOLE highlight — a partial AND is a different question', () => {
		const { view, dropped } = narrowView(
			{
				...GOOD,
				highlights: [
					{
						label: 'half real',
						when: [
							{ column: 'status', op: 'eq', value: 'shipped' },
							{ column: 'nope', op: 'eq', value: 'x' }
						]
					}
				]
			},
			COLS
		);
		expect(view?.highlights).toBeUndefined();
		expect(dropped).toContain('highlight:half real');
	});

	it('an op outside the vocabulary is dropped', () => {
		const { dropped } = narrowView(
			{ highlights: [{ label: 'x', when: [{ column: 'status', op: 'regex', value: '.*' }] }] },
			COLS
		);
		expect(dropped).toContain('highlight:x');
	});

	it('an action the renderer does not implement is refused — data cannot add a capability', () => {
		const { view, dropped } = narrowView(
			{ ...GOOD, offer: { ...GOOD.offer, action: 'delete-rows' } },
			COLS
		);
		expect(view?.offer).toBeUndefined();
		expect(dropped).toContain('offer:delete-rows');
	});

	it('an offer with no `when` is refused — a suggestion that is always on is a button', () => {
		const { view } = narrowView({ ...GOOD, offer: { label: 'x', action: VIEW_ACTIONS[0] } }, COLS);
		expect(view?.offer).toBeUndefined();
	});

	it('a non-scalar predicate value cannot smuggle an object through', () => {
		const { dropped } = narrowView(
			{
				highlights: [{ label: 'x', when: [{ column: 'status', op: 'eq', value: { $ne: null } }] }]
			},
			COLS
		);
		expect(dropped).toContain('highlight:x');
	});

	it('caps hold: 3 facets and 5 highlights are truncated, and the excess is named', () => {
		const many = Array.from({ length: 5 }, (_, i) => ({
			label: `h${i}`,
			when: [{ column: 'status', op: 'eq', value: 'shipped' }]
		}));
		const { view, dropped } = narrowView(
			{ facets: ['track', 'status', 'parent'], highlights: many },
			COLS
		);
		expect(view?.facets).toHaveLength(2);
		expect(view?.highlights).toHaveLength(4);
		expect(dropped.some((d) => d.startsWith('facet:parent'))).toBe(true);
		expect(dropped.some((d) => d.startsWith('highlight:h4'))).toBe(true);
	});

	it('a label is capped, so a 4kB "label" cannot become the layout', () => {
		const { view } = narrowView(
			{
				highlights: [
					{ label: 'x'.repeat(500), when: [{ column: 'status', op: 'eq', value: 'shipped' }] }
				]
			},
			COLS
		);
		expect(view?.highlights?.[0].label.length).toBe(48);
	});

	it('garbage in does not throw and does not invent a block', () => {
		expect(narrowView(null, COLS).view).toBeUndefined();
		expect(narrowView('not json', COLS).view).toBeUndefined();
		expect(narrowView({}, COLS).view?.style).toBe('grid');
		expect(narrowView({ style: 'kanban' }, COLS).dropped).toContain('style:kanban');
	});
});

describe('resolveView — the second, offline degrade', () => {
	it('resolves facets to columns and keeps only reachable highlights', () => {
		const r = resolveView(table(GOOD));
		expect(r.facets.map((f) => f.key)).toEqual(['track', 'status']);
		expect(r.highlights).toHaveLength(1);
		expect(r.offer?.action).toBe('focus-highlight');
	});

	it('a stale block beside changed columns degrades rather than rendering a lie', () => {
		// The offline-fallback path: the block was valid when authored, and the
		// table it arrives with no longer has those columns.
		const stale = resolveView({ ...table(GOOD), columns: [col('title', 'text')] } as DataTable);
		expect(stale.facets).toEqual([]);
		expect(stale.highlights).toEqual([]);
		expect(stale.offer).toBeNull();
		// And the style degrades on its own pre-existing rule.
		expect(stale.style).toBe('grid');
		expect(stale.degradedFrom).toBe('timeline');
	});

	it('a table with no block renders exactly as it did before this existed', () => {
		const r = resolveView(table(undefined));
		expect(r.facets).toEqual([]);
		expect(r.highlights).toEqual([]);
		expect(r.offer).toBeNull();
		expect(r.style).toBe('grid');
	});
});

describe('matchRow — the level-1 rule needs no model', () => {
	it('selects the rows the roadmap says are the most useful it can hold', () => {
		const when = resolveView(table(GOOD)).highlights[0].when;
		expect(ROWS.filter((r) => matchRow(r, when)).map((r) => r.id)).toEqual(['a']);
	});

	it('an empty predicate list matches NOTHING — never the whole table', () => {
		expect(matchRow(ROWS[0], [])).toBe(false);
	});

	it('an absent cell is the empty string, which is how "has no parent" is asked', () => {
		const roots = ROWS.filter((r) => matchRow(r, [{ column: 'parent', op: 'eq', value: '' }]));
		expect(roots.map((r) => r.id)).toEqual(['a', 'b']);
	});

	it('numbers compare as numbers, not as strings', () => {
		expect(
			matchPredicate(row({ id: 'x', ordinal: 9 }), { column: 'ordinal', op: 'lt', value: 10 })
		).toBe(true);
		// '9' < '10' is false lexically — the bug this asserts against.
		expect(
			matchPredicate(row({ id: 'x', ordinal: 9 }), { column: 'ordinal', op: 'gt', value: 10 })
		).toBe(false);
	});

	it('contains with an empty needle matches nothing, not everything', () => {
		expect(matchPredicate(ROWS[0], { column: 'status', op: 'contains', value: '' })).toBe(false);
	});
});

describe('buildViewProposalPrompt', () => {
	it('offers the model only columns that exist, and only actions that are implemented', () => {
		const p = buildViewProposalPrompt(table(undefined));
		for (const c of COLS) expect(p).toContain(c.key);
		expect(p).toContain(VIEW_ACTIONS[0]);
		expect(p).toContain('MUST be one of the keys listed above');
	});

	it('never shows a vector column — 768 floats are not a facet', () => {
		const t = { ...table(undefined), columns: [...COLS, col('embedding', 'vector')] } as DataTable;
		expect(buildViewProposalPrompt(t)).not.toContain('embedding');
	});

	it('whatever the model answers goes back through the SAME door', () => {
		// The whole point of there being no second parser: a model reply that
		// names a column it invented is refused exactly like an authored one.
		const reply = '{"facets":["track","imaginary"],"style":"timeline"}';
		const { view, dropped } = narrowView(JSON.parse(reply), COLS);
		expect(view?.facets).toEqual(['track']);
		expect(dropped).toContain('facet:imaginary');
	});
});
