import { day, isMoney, LOCALE, number } from '../fmt';

// What a mark says: its <title> (the hover tooltip) and the aria-live line use this one text.
export const tip = (series: string, x: string, y: number, locale = LOCALE) =>
	`${series} · ${day(x, locale) ?? x}: ${number(y, isMoney(series), locale)}`;
