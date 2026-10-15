import { describe, expect, it } from 'vitest';
import { layout, fmt } from './chart/geometry';
import { IDENTITY } from './chart/zoom';
import { tip } from './chart/tooltip';
import { isMoney, pickLocale, shownValue } from './fmt';

// Intl spaces are U+00A0/U+202F; the test reads them as one plain space.
const sp = (s: string) => s.replace(/\s/g, ' ');
const cs = (v: Parameters<typeof shownValue>[0], name = 'qty') => sp(shownValue(v, name, 'cs-CZ'));

describe('cs-CZ formatting (display only)', () => {
	it('a number is grouped in the shell locale', () => {
		expect(cs(12345.5)).toBe('12 345,5');
		expect(sp(shownValue(12345.5, 'qty', 'en'))).toBe('12,345.5');
	});

	it('a column that names money reads as CZK', () => {
		for (const k of ['amount', 'castka', 'Částka', 'unit_price', 'Cena (Kč)', 'total', 'sum_czk']) expect(isMoney(k), k).toBe(true);
		for (const k of ['qty', 'kcal', 'note']) expect(isMoney(k), k).toBe(false);
		expect(cs(1234.5, 'amount')).toBe('1 234,50 Kč');
	});

	it('a YYYY-MM-DD date reads d. M. yyyy; anything else stays as written', () => {
		expect(cs('2026-03-05', 'due')).toBe('5. 3. 2026');
		expect(cs('2026-02-30', 'due')).toBe('2026-02-30');
		expect(cs('2026-03-05T10:00:00Z', 'due')).toBe('2026-03-05T10:00:00Z');
		expect(cs('ACME', 'amount')).toBe('ACME');
		expect(cs(null)).toBe('');
	});

	it('the shell locale is the browser language, cs-CZ when none, en when unknown', () => {
		expect(pickLocale(undefined)).toBe('cs-CZ');
		expect(pickLocale('de-DE')).toBe('de-DE');
		expect(pickLocale('not a locale!')).toBe('en');
	});

	it('a chart labels and tooltips in the locale; the points stay raw', () => {
		expect(sp(tip('castka', '2026-03-05', 1234.5, 'cs-CZ'))).toBe('castka · 5. 3. 2026: 1 234,50 Kč');
		expect(sp(fmt(1234567, 'cs-CZ'))).toBe('1,2 mil.');
		const pts: [string, number][] = [['2026-03-05', 12345]];
		const g = layout({ chart: 'bar', x: 'category', series: [{ name: 'n', points: pts }] }, 320, IDENTITY, 'cs-CZ');
		expect(g.xLabels.map((l) => sp(l.t))).toEqual(['5. 3. 2026']);
		expect(g.yLabels.map((l) => sp(l.t))).toContain('12,3 tis.');
		expect(pts[0]).toEqual(['2026-03-05', 12345]);
	});
});
