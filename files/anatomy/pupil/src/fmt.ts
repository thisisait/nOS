// How a value reads to the person: locale grouping, CZK for money, d. M. yyyy for a date.
// Display only: the wire, the rows and anything copied out keep the raw value.
import { cell, type Value } from './wire';

/** The shell locale: the browser's language, cs-CZ when it names none, en when Intl does not know it. */
export function pickLocale(lang: string | undefined): string {
	if (!lang) return 'cs-CZ';
	try {
		return Intl.NumberFormat.supportedLocalesOf(lang).length ? lang : 'en';
	} catch {
		return 'en';
	}
}
export const LOCALE = pickLocale(globalThis.navigator?.language);

// By whole words without diacritics ("Částka", "Kč"; not "kcal", "scenario"); a word naming another
// currency or a count/rate vetoes, as the data carries no currency of its own.
const MONEY = new Set(['amount', 'castka', 'price', 'cena', 'total', 'czk', 'kc']);
const NOT = new Set(['eur', 'usd', 'gbp', 'chf', 'pln', 'huf', 'jpy', 'count', 'rows', 'qty', 'pct', 'percent', 'rate']);
export function isMoney(name: string): boolean {
	if (/[$€£¥]/.test(name)) return false;
	const w = name.replace(/([a-z])([A-Z])/g, '$1 $2').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().match(/[a-z]+/g) ?? [];
	return w.some((x) => MONEY.has(x)) && !w.some((x) => NOT.has(x));
}

// Up to 20 fraction digits: a double prints its shortest exact form, so nothing the person reads is rounded.
export const number = (v: number, money = false, locale = LOCALE) =>
	new Intl.NumberFormat(locale, { maximumFractionDigits: 20, ...(money ? { style: 'currency', currency: 'CZK' } : {}) }).format(v);

/** A change as an arrow and a sign (↑ +320, ↓ −3.5, → 0), never as colour only. */
export const signed = (d: number, locale = LOCALE) =>
	`${d > 0 ? '↑ +' : d < 0 ? '↓ −' : '→ '}${number(Math.abs(d), false, locale)}`;

/** A YYYY-MM-DD that is a real day, in the locale; null for anything else. */
export function day(s: string, locale = LOCALE): string | null {
	if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
	const t = Date.parse(s);
	if (Number.isNaN(t) || new Date(t).toISOString().slice(0, 10) !== s) return null;
	return new Intl.DateTimeFormat(locale, { timeZone: 'UTC' }).format(t);
}

/** A cell under column `name` as the person reads it. */
export function shownValue(v: Value | undefined, name: string, locale = LOCALE): string {
	if (typeof v === 'number') return number(v, isMoney(name), locale);
	if (typeof v === 'string') return day(v, locale) ?? v;
	return cell(v);
}
