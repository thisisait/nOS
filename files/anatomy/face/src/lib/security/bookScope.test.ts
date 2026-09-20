import { describe, it, expect } from 'vitest';
import { assignedBookOwners, filterBookRows, mayWriteBookRow } from './bookScope';

const ALFA = 'synthetic-client-alfa';
const BETA = 'synthetic-client-beta';
const invoices = [
	{ slug: 'inv-a', book_owner: ALFA, seller: ALFA, buyer: 'cust-a' },
	{ slug: 'inv-b', book_owner: BETA, seller: BETA, buyer: 'cust-b' }
];
const journals = [
	{ slug: 'je-a', source: 'inv-a' },
	{ slug: 'je-b', source: 'inv-b' }
];
const access = [{ slug: 'a1', principal: 'mgr-a', book_owner: ALFA }];

describe('bookScope · Model C empty access', () => {
	it('lets every manager see every book until the first assignment', () => {
		expect(assignedBookOwners([], 'mgr-a')).toBeNull();
		const rows = filterBookRows({
			slug: 'invoice',
			rows: invoices,
			uid: 'mgr-a',
			groups: ['nos-managers'],
			access: []
		});
		expect(rows).toHaveLength(2);
	});
});

describe('bookScope · second manager', () => {
	const base = {
		uid: 'mgr-b',
		groups: ['nos-managers'] as const,
		access,
		invoices,
		journals
	};

	it('hides Alfa invoices from an unassigned manager', () => {
		const rows = filterBookRows({ ...base, slug: 'invoice', rows: invoices });
		expect(rows).toEqual([]);
	});

	it('shows Alfa invoices to the assigned manager', () => {
		const rows = filterBookRows({
			...base,
			uid: 'mgr-a',
			slug: 'invoice',
			rows: invoices
		});
		expect(rows.map((r) => r.slug)).toEqual(['inv-a']);
	});

	it('does not hide from admins', () => {
		const rows = filterBookRows({
			...base,
			groups: ['nos-admins'],
			slug: 'invoice',
			rows: invoices
		});
		expect(rows).toHaveLength(2);
	});

	it('filters invoice-line / journal / posting through the invoice', () => {
		const lines = filterBookRows({
			...base,
			uid: 'mgr-a',
			slug: 'invoice-line',
			rows: [
				{ slug: 'l-a', invoice: 'inv-a' },
				{ slug: 'l-b', invoice: 'inv-b' }
			]
		});
		expect(lines.map((r) => r.slug)).toEqual(['l-a']);
		const jes = filterBookRows({
			...base,
			uid: 'mgr-a',
			slug: 'journal-entry',
			rows: journals
		});
		expect(jes.map((r) => r.slug)).toEqual(['je-a']);
		const posts = filterBookRows({
			...base,
			uid: 'mgr-a',
			slug: 'posting',
			rows: [
				{ slug: 'p-a', entry: 'je-a' },
				{ slug: 'p-b', entry: 'je-b' }
			]
		});
		expect(posts.map((r) => r.slug)).toEqual(['p-a']);
	});

	it('refuses a manager writing another client book or book-access', () => {
		expect(
			mayWriteBookRow({
				slug: 'invoice',
				row: invoices[1],
				uid: 'mgr-a',
				groups: ['nos-managers'],
				access,
				invoices
			})
		).toBe(false);
		expect(
			mayWriteBookRow({
				slug: 'book-access',
				row: access[0],
				uid: 'mgr-a',
				groups: ['nos-managers'],
				access
			})
		).toBe(false);
		expect(
			mayWriteBookRow({
				slug: 'invoice',
				row: invoices[0],
				uid: 'mgr-a',
				groups: ['nos-managers'],
				access,
				invoices
			})
		).toBe(true);
	});
});
