// A widget's rows as CSV (RFC 4180): raw values, not the locale reading fmt.ts draws. A text cell a
// spreadsheet would run as a formula (= + - @, tab, CR) gets a leading apostrophe; a number stays a number.
import { cell, type Component, type Value } from './wire';

type Results = Extract<Component, { kind: 'table_results' }>['props'];

const field = (v: Value | undefined): string => {
	let s = typeof v === 'string' ? (/^[=+\-@\t\r]/.test(v) ? `'${v}` : v) : cell(v ?? null);
	if (/[",\r\n]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
	return s;
};

/** The rows the widget shows, under its columns, one CRLF line each. */
export const toCsv = (t: Results): string =>
	[t.columns.map(field), ...t.rows.map((r) => t.columns.map((c) => field(r.cells[c])))].map((l) => `${l.join(',')}\r\n`).join('');

/** A file name export.rs accepts: [A-Za-z0-9_-]{1,64}, diacritics dropped; "rows" when nothing is left. */
export const csvName = (name: string): string =>
	name.normalize('NFD').replace(/\p{M}/gu, '').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64) || 'rows';
