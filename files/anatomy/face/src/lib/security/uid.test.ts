import { describe, it, expect } from 'vitest';
import { slugifyUid, canonicalUid } from './uid';

describe('slugifyUid — canonical contract (must match KEAP byte-for-byte)', () => {
	it('keeps a clean username unchanged', () => {
		expect(slugifyUid('akadmin')).toBe('akadmin');
		expect(slugifyUid('pazny')).toBe('pazny');
	});
	it('strips Czech diacritics to ASCII (NOT to a separator)', () => {
		expect(slugifyUid('Pázny')).toBe('pazny');
		expect(slugifyUid('Šárka Čížková')).toBe('sarka-cizkova');
		expect(slugifyUid('Řehoř')).toBe('rehor');
	});
	it('lowercases + maps every non-alphanumeric run to one dash', () => {
		expect(slugifyUid('Pazny.Develop@Gmail.com')).toBe('pazny-develop-gmail-com');
		expect(slugifyUid('John Doe')).toBe('john-doe');
		expect(slugifyUid('john_doe')).toBe('john-doe'); // underscore → dash
	});
	it('collapses dashes and trims edges', () => {
		expect(slugifyUid('--a..b__c--')).toBe('a-b-c');
		expect(slugifyUid('@@@user@@@')).toBe('user');
	});
	it('never yields a dot/slash/leading-dash (Bone _user_root safe)', () => {
		const s = slugifyUid('../../etc/passwd');
		expect(s).not.toMatch(/[./]/);
		expect(s.startsWith('-')).toBe(false);
	});
	it('caps at 64 chars', () => {
		expect(slugifyUid('x'.repeat(80)).length).toBeLessThanOrEqual(64);
	});
	it('returns empty for all-symbol / empty input', () => {
		expect(slugifyUid('@@@')).toBe('');
		expect(slugifyUid('')).toBe('');
	});
});

describe('canonicalUid — source priority username → email → uid', () => {
	it('prefers the slugified username, stable across a uid churn', () => {
		// The fix: same username → same uid, even when the raw Authentik uid
		// churns across a blank.
		expect(canonicalUid('pazny', 'p@x.eu', 'HASH_A')).toBe('pazny');
		expect(canonicalUid('pazny', 'p@x.eu', 'HASH_B_AFTER_BLANK')).toBe('pazny');
	});
	it('folds a diacritic username', () => {
		expect(canonicalUid('Pázny', '', 'HASH')).toBe('pazny');
	});
	it('falls back to the email local-part when username is empty', () => {
		expect(canonicalUid('', 'Petr.Novák@firma.cz', 'HASH')).toBe('petr-novak');
	});
	it('falls back to the sanitized raw uid as a last resort', () => {
		expect(canonicalUid('', '', 'abc123DEF')).toBe('abc123def');
	});
	it('returns empty only when everything is empty', () => {
		expect(canonicalUid('', '', '')).toBe('');
	});
});
