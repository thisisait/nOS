import { describe, it, expect } from 'vitest';
import { slugifyUid, canonicalUid } from './uid';

describe('slugifyUid', () => {
	it('keeps a clean username unchanged', () => {
		expect(slugifyUid('akadmin')).toBe('akadmin');
		expect(slugifyUid('pazny')).toBe('pazny');
	});
	it('lowercases + replaces unsafe chars with dashes', () => {
		expect(slugifyUid('Pazny.Develop@Gmail.com')).toBe('pazny-develop-gmail-com');
		expect(slugifyUid('John Doe')).toBe('john-doe');
	});
	it('collapses dashes and trims edges', () => {
		expect(slugifyUid('--a..b__c--')).toBe('a-b__c');
		expect(slugifyUid('@@@user@@@')).toBe('user');
	});
	it('never yields a dot/slash/leading-dot (Bone _user_root safe)', () => {
		const s = slugifyUid('../../etc/passwd');
		expect(s).not.toMatch(/[./]/);
		expect(s.startsWith('-')).toBe(false);
	});
	it('caps at 64 chars', () => {
		expect(slugifyUid('x'.repeat(80)).length).toBeLessThanOrEqual(64);
	});
	it('returns empty for all-symbol input', () => {
		expect(slugifyUid('@@@')).toBe('');
		expect(slugifyUid('')).toBe('');
	});
});

describe('canonicalUid', () => {
	it('prefers the slugified username', () => {
		// The key fix: same username → same uid, even when the raw Authentik uid
		// churns across a blank.
		expect(canonicalUid('pazny', 'p@x.eu', 'HASH_A')).toBe('pazny');
		expect(canonicalUid('pazny', 'p@x.eu', 'HASH_B_AFTER_BLANK')).toBe('pazny');
	});
	it('falls back to the email local-part when username is empty', () => {
		expect(canonicalUid('', 'pazny.develop@gmail.com', 'HASH')).toBe('pazny-develop');
	});
	it('falls back to the sanitized raw uid as a last resort', () => {
		expect(canonicalUid('', '', 'abc123DEF')).toBe('abc123def');
	});
	it('returns empty only when everything is empty', () => {
		expect(canonicalUid('', '', '')).toBe('');
	});
});
