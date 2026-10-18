// A widget's rows as a CSV file the person saves: RFC 4180, raw values, no formula a spreadsheet would run.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import { csvName, toCsv } from './csv';
import Widget from './Widget.svelte';

const results = (columns: string[], rows: Record<string, unknown>[]) =>
	({
		table: 't1',
		name: 'Faktury',
		query: 'all rows',
		matched: rows.length,
		total: rows.length,
		projected: false,
		columns,
		rows: rows.map((cells, i) => ({ __id: `r${i}`, cells }))
	}) as Parameters<typeof toCsv>[0];

describe('toCsv', () => {
	it('is a header of the columns and a CRLF line per row, raw values, not the locale reading', () => {
		const csv = toCsv(
			results(
				['title', 'amount', 'due'],
				[{ title: 'A', amount: 12450.5, due: '2026-11-03' }, { title: 'B' }]
			)
		);
		expect(csv).toBe('title,amount,due\r\nA,12450.5,2026-11-03\r\nB,,\r\n');
	});

	it('quotes a field holding a comma, a quote or a line break, and doubles the quote', () => {
		const csv = toCsv(
			results(
				['note'],
				[{ note: 'a, b' }, { note: 'say "hi"' }, { note: 'two\nlines' }, { note: 'cr\rhere' }]
			)
		);
		expect(csv).toBe('note\r\n"a, b"\r\n"say ""hi"""\r\n"two\nlines"\r\n"cr\rhere"\r\n');
	});

	it('prefixes a text cell a spreadsheet would read as a formula with an apostrophe', () => {
		const csv = toCsv(
			results(
				['=x', 'f'],
				[
					{ '=x': '=HYPERLINK("http://e")', f: '+1' },
					{ '=x': '-2', f: '@SUM(A1)' },
					{ '=x': 'ok', f: -5 }
				]
			)
		);
		const lines = csv.split('\r\n');
		expect(lines[0]).toBe("'=x,f");
		expect(lines[1]).toBe(`"'=HYPERLINK(""http://e"")",'+1`);
		expect(lines[2]).toBe("'-2,'@SUM(A1)");
		expect(lines[3], 'a number stays the number it is').toBe('ok,-5');
	});

	it('a leading tab or carriage return is a formula prefix too (OWASP CSV injection)', () => {
		const csv = toCsv(results(['a', 'b'], [{ a: '\t=HYPERLINK("http://e")', b: '\r=cmd' }]));
		expect(csv).toBe(`a,b\r\n"'\t=HYPERLINK(""http://e"")","'\r=cmd"\r\n`);
	});

	it('a nested value is its JSON text, a bool its word', () => {
		expect(toCsv(results(['v', 'b'], [{ v: { a: 1 }, b: true }]))).toBe(
			'v,b\r\n"{""a"":1}",true\r\n'
		);
	});
});

describe('csvName', () => {
	it('is the table name as a file name, nothing a path could read', () => {
		expect(csvName('Faktury 2026/Q3')).toBe('Faktury-2026-Q3');
		expect(csvName('../..')).toBe('rows');
		expect(csvName('x'.repeat(100)).length).toBe(64);
	});
});

describe('a rows widget offers its rows as CSV', () => {
	const box = {
		id: 'w1',
		title: 'Faktury',
		spec: { rows: { table: 't1' } },
		x: 0,
		y: 0,
		w: 6,
		h: 8
	};
	const draw = (component: unknown) =>
		render(Widget, {
			props: {
				box,
				state: { component, error: null, at: 1 } as never,
				now: 2,
				top: false,
				unit: () => ({ col: 1, row: 1 }),
				onplace() {},
				ontop() {},
				onrerun() {},
				onremove() {},
				onsubmit() {},
				onexport: async () => ''
			}
		}).body;

	it('a table_results answer has an export button; a chart has none', () => {
		expect(draw({ kind: 'table_results', props: results(['a'], [{ a: 1 }]) })).toMatch(
			/<button[^>]*aria-label="export Faktury as CSV"/
		);
		const chart = {
			kind: 'chart',
			props: { chart: 'bar', x: 'category', series: [{ name: 'n', points: [['a', 1]] }] }
		};
		expect(draw(chart)).not.toContain('as CSV');
	});
});
