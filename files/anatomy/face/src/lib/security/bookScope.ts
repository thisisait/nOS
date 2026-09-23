/**
 * Row-level book_owner isolation for praxis growth (a second manager).
 *
 * Empty book-access = Model C (every manager sees every book). Once ANY
 * assignment row exists, a manager whose Authentik uid is not listed sees
 * none of the client books. Admins (canViewAnatomy) always see all.
 *
 * Pure + unit-tested; the BFF is the only caller that matters — BooksApp's
 * client-side filter is UX, not the gate.
 */
import { canViewAnatomy } from './tier';

export const BOOK_SCOPED = new Set([
	'invoice',
	'invoice-line',
	'journal-entry',
	'posting',
	'pending-invoice-verify',
	'party',
	'account',
	'party-tax-identity',
	'party-address',
	'party-contact',
	'book-access'
]);

export type Row = Record<string, unknown>;

export function cell(row: Row, key: string): string {
	const v = row[key];
	if (v == null) return '';
	return String(v);
}

/** null = Model C (no assignments yet). Empty set = this uid has none. */
export function assignedBookOwners(access: Row[], uid: string): Set<string> | null {
	if (!access.length) return null;
	const out = new Set<string>();
	for (const r of access) {
		if (cell(r, 'principal') === uid) {
			const owner = cell(r, 'book_owner');
			if (owner) out.add(owner);
		}
	}
	return out;
}

export function filterBookRows(opts: {
	slug: string;
	rows: Row[];
	uid: string;
	groups?: readonly string[];
	access: Row[];
	invoices?: Row[];
	journals?: Row[];
}): Row[] {
	if (canViewAnatomy(opts.groups)) return opts.rows;
	if (!BOOK_SCOPED.has(opts.slug)) return opts.rows;
	const owners = assignedBookOwners(opts.access, opts.uid);
	if (owners === null) return opts.rows;
	const invoices = opts.invoices ?? [];
	const journals = opts.journals ?? [];
	const invSlugs = new Set(
		invoices
			.filter((i) => owners.has(cell(i, 'book_owner')))
			.map((i) => cell(i, 'slug') || cell(i, 'id'))
	);
	const jeSlugs = new Set(
		journals
			.filter((j) => invSlugs.has(cell(j, 'source')))
			.map((j) => cell(j, 'slug') || cell(j, 'id'))
	);
	const counterparties = new Set<string>();
	for (const i of invoices) {
		if (!invSlugs.has(cell(i, 'slug') || cell(i, 'id'))) continue;
		for (const k of ['seller', 'buyer', 'book_owner'] as const) {
			const v = cell(i, k);
			if (v) counterparties.add(v);
		}
	}

	return opts.rows.filter((r) => {
		switch (opts.slug) {
			case 'book-access':
				return cell(r, 'principal') === opts.uid;
			case 'invoice':
				return owners.has(cell(r, 'book_owner'));
			case 'invoice-line':
				return invSlugs.has(cell(r, 'invoice'));
			case 'journal-entry':
				return invSlugs.has(cell(r, 'source'));
			case 'posting':
				return jeSlugs.has(cell(r, 'entry'));
			case 'pending-invoice-verify': {
				if (owners.has(cell(r, 'book_owner'))) return true;
				const blob = JSON.stringify(r.fields ?? r);
				return [...owners].some((o) => blob.includes(o));
			}
			case 'party':
				return owners.has(cell(r, 'slug')) || counterparties.has(cell(r, 'slug'));
			case 'account': {
				const party = cell(r, 'party');
				return !party || owners.has(party);
			}
			case 'party-tax-identity':
			case 'party-address':
			case 'party-contact':
				return owners.has(cell(r, 'party'));
			default:
				return false;
		}
	});
}

export function mayWriteBookRow(opts: {
	slug: string;
	row: Row;
	uid: string;
	groups?: readonly string[];
	access: Row[];
	invoices?: Row[];
}): boolean {
	if (canViewAnatomy(opts.groups)) return true;
	if (opts.slug === 'book-access') return false;
	if (!BOOK_SCOPED.has(opts.slug)) return true;
	const owners = assignedBookOwners(opts.access, opts.uid);
	if (owners === null) return true;
	const filtered = filterBookRows({
		slug: opts.slug,
		rows: [opts.row],
		uid: opts.uid,
		groups: opts.groups,
		access: opts.access,
		invoices: opts.invoices
	});
	return filtered.length === 1;
}
