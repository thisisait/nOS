import { describe, expect, it } from 'vitest';
import { validateViewMeta } from './table';

/**
 * D5 client-filter-view — RETRO-RED: before this commit `FACETABLE` was
 * `['select', 'text', 'boolean', 'user', 'taxonomyRef']` and did not include
 * `rowRef`, so `invoice.table.yml`'s `view: {facets: [book_owner]}` (book_owner
 * is kind:rowRef) would have been REFUSED by this exact validator at author
 * time — "view.facets[0] must name a low-cardinality column, got rowRef".
 */
describe('validateViewMeta — rowRef facets', () => {
	const columns = [
		{ key: 'book_owner', kind: 'rowRef' },
		{ key: 'notes', kind: 'json' }
	];

	it('accepts a facet on a rowRef column (the client picker)', () => {
		const errors = validateViewMeta({ facets: ['book_owner'] }, columns);
		expect(errors).toEqual([]);
	});

	it('still refuses a facet on a genuinely high-cardinality/free-form kind', () => {
		const errors = validateViewMeta({ facets: ['notes'] }, columns);
		expect(errors).toEqual(['view.facets[0] must name a low-cardinality column, got json']);
	});
});
