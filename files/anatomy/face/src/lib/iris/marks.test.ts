import { describe, it, expect } from 'vitest';
import { mark, type Catalogue } from './marks';

const cat: Catalogue = {
	tables: [
		{
			id: 'invoices',
			title: 'Faktury',
			columns: [
				{
					key: 'customer',
					label: 'Zákazník',
					kind: 'select',
					options: ['Acme', 'Acme Corp', 'Beta']
				},
				{ key: 'due_date', label: 'Splatnost', kind: 'date' }
			]
		},
		{
			id: 'orders',
			title: 'Orders',
			columns: [{ key: 'total', label: 'Total amount', kind: 'number' }]
		},
		{ id: 'notes', title: 'Notes', columns: [] }
	]
};
const empty: Catalogue = { tables: [] };

/** [text slice, kind, ref] per span, so a failure reads as the sentence. */
const show = (text: string, c: Catalogue) =>
	mark(text, c).map((s) => [text.slice(s.start, s.end), s.kind, s.ref]);

describe('mark', () => {
	it('marks table, operator, date, period and option, nothing on free words', () => {
		expect(show('faktury mezi 1.1. a dnes pro Acme', cat)).toEqual([
			['faktury', 'table', 'invoices'],
			['mezi', 'operator', 'between'],
			['1.1.', 'date', undefined],
			['dnes', 'period', 'today'],
			['Acme', 'option', 'invoices.customer=Acme']
		]);
	});

	it('marks the row example in English', () => {
		expect(show('orders between 1.1. and today for Acme', cat)).toEqual([
			['orders', 'table', 'orders'],
			['between', 'operator', 'between'],
			['1.1.', 'date', undefined],
			['today', 'period', 'today'],
			['Acme', 'option', 'invoices.customer=Acme']
		]);
	});

	it('longest match wins', () => {
		expect(show('Acme Corp total amount', cat)).toEqual([
			['Acme Corp', 'option', 'invoices.customer=Acme Corp'],
			['total amount', 'column', 'orders.total']
		]);
		expect(show('minulý měsíc', empty)).toEqual([['minulý měsíc', 'period', 'last_month']]);
		expect(show('top 5', empty)).toEqual([['top 5', 'operator', 'top']]);
	});

	it('is case- and diacritics-insensitive, offsets stay on the original text', () => {
		expect(show('ZAKAZNIK a zákazník', cat)).toEqual([
			['ZAKAZNIK', 'column', 'invoices.customer'],
			['zákazník', 'column', 'invoices.customer']
		]);
		expect(show('víc než 3 a vice nez 4', empty).map((s) => s[0])).toEqual([
			'víc než',
			'3',
			'vice nez',
			'4'
		]);
	});

	it('never matches inside a longer word', () => {
		expect(show('notesbook acmeish dnesek orders2 summary', cat)).toEqual([]);
	});

	it('marks keys and ids too', () => {
		expect(show('invoices due_date', cat)).toEqual([
			['invoices', 'table', 'invoices'],
			['due_date', 'column', 'invoices.due_date']
		]);
	});

	it('an empty catalogue still marks dates, numbers and operators', () => {
		expect(show('od 2026-01-05 do 3.2.2026 víc než 12,5 a průměr', empty)).toEqual([
			['2026-01-05', 'date', undefined],
			['3.2.2026', 'date', undefined],
			['víc než', 'operator', 'gt'],
			['12,5', 'number', undefined],
			['průměr', 'operator', 'avg']
		]);
		expect(mark('', empty)).toEqual([]);
	});

	it('spans never overlap and come in text order', () => {
		const spans = mark('Faktury Acme Corp 1.1.2026 sum count this month', cat);
		for (let i = 1; i < spans.length; i++)
			expect(spans[i].start).toBeGreaterThanOrEqual(spans[i - 1].end);
		expect(spans.map((s) => s.kind)).toEqual([
			'table',
			'option',
			'date',
			'operator',
			'operator',
			'period'
		]);
	});
});
